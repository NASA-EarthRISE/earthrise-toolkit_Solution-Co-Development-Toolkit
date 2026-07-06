"""
Management command: reingest every IngestedDocument DB record whose chunks
are absent from the current vector store.

Typical use case: the store was wiped or replaced (e.g. switching from local
Chroma to the shared embedding service) leaving stale DB records that point
to documents not yet loaded into the new store.

Usage
-----
  # Dry-run — show what would be reingested without touching anything
  python manage.py reingest_missing --dry-run

  # Reingest all missing documents
  python manage.py reingest_missing

  # Also delete any chunks whose source filename has no DB record (orphans)
  python manage.py reingest_missing --purge-orphans
"""

import os

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

_PAGE_SIZE = 500


class Command(BaseCommand):
    help = (
        "Reingest every registered document whose chunks are missing from the "
        "current vector store."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Report what would happen without making any changes.",
        )
        parser.add_argument(
            "--purge-orphans",
            action="store_true",
            default=False,
            help=(
                "Also delete chunks in the store whose source filename has no "
                "matching IngestedDocument record (e.g. leaked session uploads)."
            ),
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        dry_run       = options["dry_run"]
        purge_orphans = options["purge_orphans"]

        mode = (getattr(settings, "RAG_MODE", "local") or "local").lower()
        if mode not in ("shared", "local"):
            raise CommandError(
                f"RAG_MODE='{mode}' (proxy) is not supported by this command."
            )

        upload_dir = os.path.join(settings.BASE_DIR, "uploads")

        # --- 1. Get what is already in the store ---
        self.stdout.write("Fetching current store contents ...")
        sources_in_store = self._get_sources_in_store(mode)
        self.stdout.write(f"  {len(sources_in_store)} distinct source(s) in store.")

        # --- 2. Get all registered DB records ---
        from webapp.models import IngestedDocument
        db_docs = list(IngestedDocument.objects.order_by("display_name"))
        self.stdout.write(f"  {len(db_docs)} IngestedDocument record(s) in database.\n")

        db_filenames = {doc.filename for doc in db_docs}

        # --- 3. Identify missing documents ---
        missing = [doc for doc in db_docs if doc.filename not in sources_in_store]
        present = [doc for doc in db_docs if doc.filename in sources_in_store]

        if present:
            self.stdout.write("Already in store (will skip):")
            for doc in present:
                self.stdout.write(f"  ✓  {doc.filename}")
            self.stdout.write("")

        if not missing:
            self.stdout.write(self.style.SUCCESS("All registered documents are already in the store."))
        else:
            self.stdout.write(
                f"{'[DRY RUN] ' if dry_run else ''}Documents to reingest ({len(missing)}):"
            )
            for doc in missing:
                filepath = os.path.join(upload_dir, doc.filename)
                exists   = os.path.isfile(filepath)
                status   = "file found" if exists else "FILE MISSING from uploads/"
                self.stdout.write(f"  •  {doc.filename}  [{status}]")
            self.stdout.write("")

            if not dry_run:
                self._reingest_documents(missing, upload_dir, mode)

        # --- 4. Optionally purge orphan chunks ---
        orphan_sources = [s for s in sources_in_store if s not in db_filenames]
        if orphan_sources:
            self.stdout.write(
                f"\nOrphan sources in store (no DB record)  — {len(orphan_sources)} source(s):"
            )
            for src in sorted(orphan_sources):
                chunk_count = sources_in_store[src]
                self.stdout.write(f"  ⚠  {src}  ({chunk_count} chunks)")

            if purge_orphans and not dry_run:
                self.stdout.write("")
                self._purge_orphans(orphan_sources, mode)
            elif purge_orphans and dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        "  --dry-run: orphans would be deleted with --purge-orphans."
                    )
                )
            else:
                self.stdout.write(
                    "  Run with --purge-orphans to remove these from the store."
                )

        if dry_run:
            self.stdout.write(self.style.WARNING("\n--dry-run: no changes were made."))

    # ------------------------------------------------------------------
    def _get_sources_in_store(self, mode):
        """Return {source_filename: chunk_count} for everything in the store."""
        if mode == "shared":
            return self._get_sources_shared()
        else:
            return self._get_sources_local()

    def _get_sources_shared(self):
        base       = getattr(settings, "SHARED_EMBEDDING_SERVICE_URL", "http://localhost:8000").rstrip("/")
        api_key    = getattr(settings, "SHARED_EMBEDDING_SERVICE_API_KEY", "")
        collection = getattr(settings, "CHROMA_COLLECTION", "pi_assist_docs")
        headers    = {"X-API-Key": api_key, "Content-Type": "application/json"}

        sources = {}
        offset  = 0
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
                raise CommandError(f"Could not list store contents: {exc}\n{resp.text}")

            data  = resp.json()
            ids   = data.get("ids", [])
            metas = data.get("metadatas", []) or ([{}] * len(ids))

            if not ids:
                break

            for meta in metas:
                src = (meta or {}).get("source")
                if src:
                    sources[src] = sources.get(src, 0) + 1

            if len(ids) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        return sources

    def _get_sources_local(self):
        import chromadb
        from pathlib import Path

        persist_dir     = getattr(settings, "CHROMA_PERSIST_DIR", "chroma_db")
        base_dir        = Path(settings.BASE_DIR)
        persist_dir     = str(base_dir / persist_dir)
        collection_name = getattr(settings, "CHROMA_COLLECTION", "pi_assist_docs")

        client     = chromadb.PersistentClient(path=persist_dir)
        collection = client.get_or_create_collection(name=collection_name)
        result     = collection.get(limit=10000)
        metas      = result.get("metadatas", []) or []
        sources    = {}
        for meta in metas:
            src = (meta or {}).get("source")
            if src:
                sources[src] = sources.get(src, 0) + 1
        return sources

    # ------------------------------------------------------------------
    def _reingest_documents(self, docs, upload_dir, mode):
        from webapp.ingest_helpers import extract_text_and_chunk
        from webapp.rag import get_store
        from webapp.document_registry import register_document

        store        = get_store()
        ok_count     = 0
        skip_count   = 0
        error_count  = 0

        for doc in docs:
            filepath = os.path.join(upload_dir, doc.filename)

            if not os.path.isfile(filepath):
                self.stdout.write(
                    self.style.ERROR(
                        f"  SKIP  {doc.filename} — file not found in uploads/"
                    )
                )
                skip_count += 1
                continue

            self.stdout.write(f"  Ingesting  {doc.filename} ...")
            try:
                chunks = extract_text_and_chunk(filepath)
                if not chunks:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  WARN  {doc.filename} produced 0 chunks — skipping."
                        )
                    )
                    skip_count += 1
                    continue

                for chunk in chunks:
                    chunk["metadata"]["is_global"] = True
                    chunk["metadata"].setdefault("tag", "admin-upload")

                store.upsert(chunks)

                register_document(
                    display_name=doc.display_name,
                    filename=doc.filename,
                    file_path=filepath,
                    chunk_count=len(chunks),
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  OK    {doc.filename} — {len(chunks)} chunks ingested."
                    )
                )
                ok_count += 1

            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(f"  ERROR {doc.filename} — {exc}")
                )
                error_count += 1

        self.stdout.write(
            f"\nReingest complete: {ok_count} succeeded, "
            f"{skip_count} skipped, {error_count} errors."
        )

    # ------------------------------------------------------------------
    def _purge_orphans(self, orphan_sources, mode):
        """Delete all chunks from the store whose source is in orphan_sources."""
        if mode == "shared":
            self._purge_orphans_shared(orphan_sources)
        else:
            self._purge_orphans_local(orphan_sources)

    def _purge_orphans_shared(self, orphan_sources):
        base       = getattr(settings, "SHARED_EMBEDDING_SERVICE_URL", "http://localhost:8000").rstrip("/")
        api_key    = getattr(settings, "SHARED_EMBEDDING_SERVICE_API_KEY", "")
        collection = getattr(settings, "CHROMA_COLLECTION", "pi_assist_docs")
        headers    = {"X-API-Key": api_key, "Content-Type": "application/json"}

        orphan_set = set(orphan_sources)

        # Fetch all IDs and filter to orphan sources
        ids_to_delete = []
        offset        = 0
        while True:
            resp = requests.get(
                f"{base}/collections/{collection}/documents",
                params={"limit": _PAGE_SIZE, "offset": offset},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            data  = resp.json()
            ids   = data.get("ids", [])
            metas = data.get("metadatas", []) or ([{}] * len(ids))

            if not ids:
                break

            for doc_id, meta in zip(ids, metas):
                if (meta or {}).get("source") in orphan_set:
                    ids_to_delete.append(doc_id)

            if len(ids) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        if not ids_to_delete:
            self.stdout.write("  No orphan chunks found to delete.")
            return

        del_resp = requests.delete(
            f"{base}/collections/{collection}/documents",
            json={"ids": ids_to_delete},
            headers=headers,
            timeout=60,
        )
        del_resp.raise_for_status()
        self.stdout.write(
            self.style.SUCCESS(
                f"  Deleted {len(ids_to_delete)} orphan chunk(s) from store."
            )
        )

    def _purge_orphans_local(self, orphan_sources):
        import chromadb
        from pathlib import Path

        persist_dir     = str(Path(settings.BASE_DIR) / getattr(settings, "CHROMA_PERSIST_DIR", "chroma_db"))
        collection_name = getattr(settings, "CHROMA_COLLECTION", "pi_assist_docs")
        client          = chromadb.PersistentClient(path=persist_dir)
        collection      = client.get_or_create_collection(name=collection_name)

        total_deleted = 0
        for src in orphan_sources:
            collection.delete(where={"source": src})
            self.stdout.write(self.style.SUCCESS(f"  Deleted orphan chunks for: {src}"))
            total_deleted += 1
        self.stdout.write(f"  Purged {total_deleted} orphan source(s).")
