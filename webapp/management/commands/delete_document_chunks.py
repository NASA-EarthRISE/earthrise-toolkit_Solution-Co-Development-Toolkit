"""
Management command: delete all vector-store chunks for a specific document,
then optionally re-ingest it.

Works in shared-embedding-service mode (RAG_MODE=shared).
Also works in local Chroma mode (RAG_MODE=local).

Usage examples
--------------
  # Dry-run — show what would be deleted without touching anything
  python manage.py delete_document_chunks "Cover and preface.pdf" --dry-run

  # Delete only (re-ingest manually afterwards via the admin upload UI)
  python manage.py delete_document_chunks "Cover and preface.pdf"

  # Delete then immediately re-ingest from the uploads/ directory
  python manage.py delete_document_chunks "Cover and preface.pdf" --reingest
"""

import os
import sys

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


# How many documents to fetch per pagination page when listing the collection.
_PAGE_SIZE = 500


class Command(BaseCommand):
    help = "Delete all vector-store chunks for a named document (by source filename)."

    def add_arguments(self, parser):
        parser.add_argument(
            "filename",
            type=str,
            help='Exact filename as stored in chunk metadata, e.g. "Cover and preface.pdf"',
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="List matching chunks but do not delete them.",
        )
        parser.add_argument(
            "--reingest",
            action="store_true",
            default=False,
            help=(
                "After deleting, re-ingest the file from the uploads/ directory. "
                "The file must exist at uploads/<filename>."
            ),
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        filename = options["filename"]
        dry_run  = options["dry_run"]
        reingest = options["reingest"]

        mode = (getattr(settings, "RAG_MODE", "local") or "local").lower()
        self.stdout.write(f"RAG mode: {mode}")

        if mode == "shared":
            self._handle_shared(filename, dry_run, reingest)
        elif mode == "local":
            self._handle_local(filename, dry_run, reingest)
        else:
            raise CommandError(
                f"RAG_MODE='{mode}' (proxy) does not expose a delete API through this app. "
                "Delete the document via the LiteLLM proxy admin interface directly."
            )

    # ------------------------------------------------------------------
    # Shared Embedding Service path
    # ------------------------------------------------------------------
    def _handle_shared(self, filename, dry_run, reingest):
        base       = getattr(settings, "SHARED_EMBEDDING_SERVICE_URL", "http://localhost:8000").rstrip("/")
        api_key    = getattr(settings, "SHARED_EMBEDDING_SERVICE_API_KEY", "")
        collection = getattr(settings, "CHROMA_COLLECTION", "pi_assist_docs")
        headers    = {"X-API-Key": api_key, "Content-Type": "application/json"}

        self.stdout.write(f"Collection : {collection}")
        self.stdout.write(f"Service    : {base}")
        self.stdout.write(f"Searching for chunks with source='{filename}' ...")

        # --- Paginate through all documents and collect matching IDs ---
        matching_ids  = []
        matching_meta = []
        offset        = 0

        while True:
            resp = requests.get(
                f"{base}/collections/{collection}/documents",
                params={"limit": _PAGE_SIZE, "offset": offset},
                headers=headers,
                timeout=30,
            )
            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:
                raise CommandError(f"Failed to list collection documents: {exc}\n{resp.text}")

            data      = resp.json()
            ids       = data.get("ids", [])
            metadatas = data.get("metadatas", []) or ([{}] * len(ids))

            if not ids:
                break  # reached the end

            for doc_id, meta in zip(ids, metadatas):
                if (meta or {}).get("source") == filename:
                    matching_ids.append(doc_id)
                    matching_meta.append(meta or {})

            if len(ids) < _PAGE_SIZE:
                break  # last page
            offset += _PAGE_SIZE

        # --- Report what was found ---
        if not matching_ids:
            self.stdout.write(
                self.style.WARNING(
                    f"\nNo chunks found with source='{filename}'. "
                    "Check that the filename matches exactly (including extension and capitalisation)."
                )
            )
            # Still honour --reingest if requested, so a fresh first-time
            # ingest works even when nothing existed before.
        else:
            chunk_types = {}
            for meta in matching_meta:
                ct = meta.get("chunk_type", "unknown")
                chunk_types[ct] = chunk_types.get(ct, 0) + 1

            self.stdout.write(
                self.style.SUCCESS(f"\nFound {len(matching_ids)} chunks for '{filename}':")
            )
            for ct, n in sorted(chunk_types.items()):
                self.stdout.write(f"  {ct:10s}  {n} chunks")

            if dry_run:
                self.stdout.write(
                    self.style.WARNING("\n--dry-run flag set. No chunks were deleted.")
                )
            else:
                self.stdout.write(f"\nDeleting {len(matching_ids)} chunks ...")
                del_resp = requests.delete(
                    f"{base}/collections/{collection}/documents",
                    json={"ids": matching_ids},
                    headers=headers,
                    timeout=60,
                )
                try:
                    del_resp.raise_for_status()
                except requests.HTTPError as exc:
                    raise CommandError(f"Delete request failed: {exc}\n{del_resp.text}")

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Deleted {len(matching_ids)} chunks for '{filename}'."
                    )
                )

                # Update the IngestedDocument record in the database
                try:
                    from webapp.models import IngestedDocument
                    deleted_count, _ = IngestedDocument.objects.filter(filename=filename).delete()
                    if deleted_count:
                        self.stdout.write(f"Removed database record for '{filename}'.")
                except Exception as exc:
                    self.stdout.write(
                        self.style.WARNING(f"Could not remove database record: {exc}")
                    )

        # --- Optionally re-ingest ---
        if reingest and not dry_run:
            self._reingest(filename)

    # ------------------------------------------------------------------
    # Local Chroma path
    # ------------------------------------------------------------------
    def _handle_local(self, filename, dry_run, reingest):
        import chromadb
        from chromadb.utils import embedding_functions as ef

        persist_dir = getattr(settings, "CHROMA_PERSIST_DIR", None)
        if not persist_dir:
            from pathlib import Path
            persist_dir = str(Path(settings.BASE_DIR) / "chroma_db")
        collection_name = getattr(settings, "CHROMA_COLLECTION", "pi_assist_docs")

        self.stdout.write(f"Collection : {collection_name}")
        self.stdout.write(f"Chroma dir : {persist_dir}")
        self.stdout.write(f"Searching for chunks with source='{filename}' ...")

        client     = chromadb.PersistentClient(path=persist_dir)
        model_name = getattr(settings, "LOCAL_EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
        emb_fn     = ef.SentenceTransformerEmbeddingFunction(model_name=model_name)
        collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=emb_fn,
        )

        result = collection.get(where={"source": filename})
        ids = result.get("ids", [])
        metas = result.get("metadatas", []) or []

        if not ids:
            self.stdout.write(
                self.style.WARNING(
                    f"\nNo chunks found with source='{filename}'."
                )
            )
        else:
            chunk_types = {}
            for meta in metas:
                ct = (meta or {}).get("chunk_type", "unknown")
                chunk_types[ct] = chunk_types.get(ct, 0) + 1

            self.stdout.write(
                self.style.SUCCESS(f"\nFound {len(ids)} chunks for '{filename}':")
            )
            for ct, n in sorted(chunk_types.items()):
                self.stdout.write(f"  {ct:10s}  {n} chunks")

            if dry_run:
                self.stdout.write(
                    self.style.WARNING("\n--dry-run flag set. No chunks were deleted.")
                )
            else:
                collection.delete(where={"source": filename})
                self.stdout.write(
                    self.style.SUCCESS(f"Deleted {len(ids)} chunks for '{filename}'.")
                )

                try:
                    from webapp.models import IngestedDocument
                    deleted_count, _ = IngestedDocument.objects.filter(filename=filename).delete()
                    if deleted_count:
                        self.stdout.write(f"Removed database record for '{filename}'.")
                except Exception as exc:
                    self.stdout.write(
                        self.style.WARNING(f"Could not remove database record: {exc}")
                    )

        if reingest and not dry_run:
            self._reingest(filename)

    # ------------------------------------------------------------------
    # Re-ingest helper (shared by both modes)
    # ------------------------------------------------------------------
    def _reingest(self, filename):
        upload_dir = os.path.join(settings.BASE_DIR, "uploads")
        filepath   = os.path.join(upload_dir, filename)

        if not os.path.isfile(filepath):
            raise CommandError(
                f"--reingest requested but '{filepath}' does not exist. "
                "Place the file in the uploads/ directory and try again."
            )

        self.stdout.write(f"\nRe-ingesting '{filename}' ...")

        from webapp.ingest_helpers import extract_text_and_chunk
        from webapp.rag import get_store
        from webapp.document_registry import register_document

        chunks = extract_text_and_chunk(filepath)
        if not chunks:
            raise CommandError(
                f"extract_text_and_chunk returned 0 chunks for '{filename}'. "
                "The file may be empty or image-only."
            )

        # Mark every chunk as global (not session-scoped)
        for chunk in chunks:
            chunk["metadata"]["is_global"] = True

        store = get_store()
        store.upsert(chunks)

        register_document(
            display_name=os.path.splitext(filename)[0],
            filename=filename,
            file_path=filepath,
            chunk_count=len(chunks),
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Re-ingested '{filename}': {len(chunks)} chunks upserted."
            )
        )
