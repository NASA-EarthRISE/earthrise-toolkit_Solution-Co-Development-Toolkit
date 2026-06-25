# pi_assist/document_registry.py
"""
Helpers for registering and listing ingested global knowledge-base documents.
"""

import os
from urllib.parse import quote

# The combined single-PDF release of the full toolkit.  It is always offered
# as a download at the top of the document list when present on disk, whether
# or not it has been separately indexed into the RAG store.
_FULL_TOOLKIT_FILENAME = "MSFC Solution Co-Development Toolkit V0.1.pdf"
_FULL_TOOLKIT_LABEL    = "MSFC Solution Co-Development Toolkit V0.1 — Complete Collection"


def register_document(display_name: str, filename: str, file_path: str, chunk_count: int = 0):
    """
    Upsert a document record in the database keyed on file_path.
    Re-running ingest will update chunk_count rather than creating duplicates.
    """
    from .models import IngestedDocument
    IngestedDocument.objects.update_or_create(
        file_path=file_path,
        defaults={
            "display_name": display_name,
            "filename": filename,
            "chunk_count": chunk_count,
        },
    )


def get_document_list_prompt() -> str:
    """
    Return a system-prompt block that lists every registered knowledge-base
    document with a clickable Markdown download link.

    The LLM is instructed to present this list verbatim when a user asks what
    documents are available. Wrapped in try/except so a missing migration
    (first run before migrate) will not crash the chat endpoint.
    """
    try:
        from django.conf import settings
        from .models import IngestedDocument

        docs = list(IngestedDocument.objects.order_by("display_name"))

        # Check whether the full combined PDF exists on disk
        uploads_dir = os.path.join(settings.BASE_DIR, "uploads")
        full_pdf_on_disk = os.path.isfile(
            os.path.join(uploads_dir, _FULL_TOOLKIT_FILENAME)
        )
        full_pdf_in_db = any(d.filename == _FULL_TOOLKIT_FILENAME for d in docs)

        if not docs and not full_pdf_on_disk:
            return ""

        lines = [
            "## Knowledge Base Documents",
            "",
            "The following documents are loaded into the knowledge base.",
            "When a user asks which documents are available, what is in the knowledge base,",
            "or what files you have access to, present this exact list with the download links",
            "as Markdown hyperlinks so the user can click to download each file:",
            "",
        ]

        # Always list the full combined toolkit PDF first when it exists on disk
        # and is not already coming from the database query below.
        if full_pdf_on_disk and not full_pdf_in_db:
            url = f"/api/documents/{quote(_FULL_TOOLKIT_FILENAME)}"
            lines.append(f"- [{_FULL_TOOLKIT_LABEL}]({url})")

        for doc in docs:
            url = f"/api/documents/{quote(doc.filename)}"
            # Pin the full PDF label even if it was ingested through the upload tool
            label = _FULL_TOOLKIT_LABEL if doc.filename == _FULL_TOOLKIT_FILENAME else doc.display_name
            lines.append(f"- [{label}]({url}) ({doc.chunk_count} chunks)")

        return "\n".join(lines)

    except Exception:
        return ""
