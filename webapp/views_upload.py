# pi_assist/views_upload.py

import os
import logging
import traceback
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required

from .rag import get_store
from .ingest_helpers import extract_text_and_chunk
from .document_registry import register_document

LOG = logging.getLogger(__name__)

UPLOAD_DIR = os.path.join(settings.BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@staff_member_required
def upload_page(request):
    return render(request, "webapp/upload.html")


@csrf_exempt
@staff_member_required
def upload_file(request):
    file = request.FILES.get("file")
    if not file:
        return JsonResponse({"message": "No file received"}, status=400)

    save_path = os.path.join(UPLOAD_DIR, file.name)

    # Write file to disk
    with open(save_path, "wb") as f:
        for chunk in file.chunks():
            f.write(chunk)

    # Extract → Chunk → Upsert into the shared singleton store
    try:
        store = get_store()
        store_type = type(store).__name__
        LOG.info(f"[upload] Store type: {store_type}  file: {file.name}")

        docs = extract_text_and_chunk(save_path)
        LOG.info(f"[upload] Extracted {len(docs)} chunks from '{file.name}'")

        if not docs:
            return JsonResponse(
                {"message": f"WARNING: '{file.name}' produced 0 chunks — file may be empty or image-only."},
                status=400,
            )

        # Tag each chunk as a global knowledge-base document
        for d in docs:
            d["metadata"]["is_global"] = True
            d["metadata"].setdefault("tag", "admin-upload")

        LOG.info(f"[upload] Upserting {len(docs)} chunks via {store_type} ...")
        store.upsert(docs)
        LOG.info(f"[upload] Upsert complete for '{file.name}'")

        # Register in the Django DB so the document appears in the
        # knowledge-base list with a download link in every chat session.
        register_document(
            display_name=file.name,
            filename=file.name,
            file_path=os.path.abspath(save_path),
            chunk_count=len(docs),
        )

        return JsonResponse({"message": f"File '{file.name}' ingested ({len(docs)} chunks) via {store_type}."})

    except Exception as e:
        tb = traceback.format_exc()
        LOG.error(f"[upload] ERROR ingesting '{file.name}': {e}\n{tb}")
        return JsonResponse({"message": f"ERROR ingesting {file.name}: {e}"}, status=500)
