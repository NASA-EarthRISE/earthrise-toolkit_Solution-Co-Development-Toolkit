"""
Management command: report the current RAG configuration and collection state.

Run this on any environment to confirm which store is active, whether it is
reachable, and what documents are loaded.

Usage
-----
  python manage.py rag_status
"""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

_PAGE_SIZE = 500


class Command(BaseCommand):
    help = "Report RAG mode, connectivity, and collection contents."

    def handle(self, *args, **options):
        mode = (getattr(settings, "RAG_MODE", "local") or "local").lower()

        self.stdout.write("=" * 60)
        self.stdout.write("  RAG STATUS REPORT")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  RAG_MODE : {mode}")

        if mode == "shared":
            self._check_shared()
        elif mode == "local":
            self._check_local()
        else:
            self.stdout.write(f"  Mode '{mode}' (proxy) — no local diagnostics available.")

        self.stdout.write("=" * 60)

    # ------------------------------------------------------------------
    def _check_shared(self):
        base       = getattr(settings, "SHARED_EMBEDDING_SERVICE_URL", "http://localhost:8000").rstrip("/")
        api_key    = getattr(settings, "SHARED_EMBEDDING_SERVICE_API_KEY", "")
        collection = getattr(settings, "CHROMA_COLLECTION", "pi_assist_docs")
        headers    = {"X-API-Key": api_key, "Content-Type": "application/json"}

        self.stdout.write(f"  SERVICE  : {base}")
        self.stdout.write(f"  COLLECTION: {collection}")
        self.stdout.write("")

        # --- Connectivity check ---
        try:
            resp = requests.get(f"{base}/collections", headers=headers, timeout=10)
            resp.raise_for_status()
            self.stdout.write(self.style.SUCCESS("  [OK] Shared embedding service is reachable."))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  [FAIL] Cannot reach shared embedding service: {exc}"))
            self.stdout.write(self.style.WARNING(
                "\n  NOTE: When the service is unreachable the app silently falls back to\n"
                "  'No retrieved context' and the LLM answers from training data only.\n"
                "  Users see responses but they are NOT grounded in toolkit documents."
            ))
            return

        # --- Collection existence check ---
        try:
            collections_data = resp.json()
            names = [c.get("name") or c for c in collections_data] if isinstance(collections_data, list) else []
            if collection in names:
                self.stdout.write(self.style.SUCCESS(f"  [OK] Collection '{collection}' exists."))
            else:
                self.stdout.write(self.style.WARNING(
                    f"  [WARN] Collection '{collection}' not found on service. "
                    f"Available: {names or '(none)'}"
                ))
        except Exception:
            pass  # collection listing not critical

        # --- Document inventory ---
        try:
            all_ids   = []
            all_metas = []
            offset    = 0

            while True:
                r = requests.get(
                    f"{base}/collections/{collection}/documents",
                    params={"limit": _PAGE_SIZE, "offset": offset},
                    headers=headers,
                    timeout=30,
                )
                r.raise_for_status()
                data  = r.json()
                ids   = data.get("ids", [])
                metas = data.get("metadatas", []) or ([{}] * len(ids))
                all_ids.extend(ids)
                all_metas.extend(metas)
                if len(ids) < _PAGE_SIZE:
                    break
                offset += _PAGE_SIZE

        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  [FAIL] Could not list collection documents: {exc}"))
            return

        total = len(all_ids)
        self.stdout.write(f"\n  Total chunks : {total}")

        if total == 0:
            self.stdout.write(self.style.ERROR(
                "\n  [EMPTY] The collection contains no chunks.\n"
                "  All documents need to be ingested before the AI assistant\n"
                "  can give grounded answers."
            ))
            return

        # Tally by source
        sources = {}
        for meta in all_metas:
            src = (meta or {}).get("source", "UNKNOWN")
            ct  = (meta or {}).get("chunk_type", "other")
            if src not in sources:
                sources[src] = {"parent": 0, "child": 0, "other": 0}
            if ct == "parent":
                sources[src]["parent"] += 1
            elif ct == "child":
                sources[src]["child"] += 1
            else:
                sources[src]["other"] += 1

        self.stdout.write(f"  Documents    : {len(sources)}\n")
        self.stdout.write(f"  {'Source':<50} {'parent':>7} {'child':>7} {'other':>7}  {'total':>7}")
        self.stdout.write("  " + "-" * 76)
        for src, counts in sorted(sources.items()):
            row_total = sum(counts.values())
            self.stdout.write(
                f"  {src:<50} {counts['parent']:>7} {counts['child']:>7} "
                f"{counts['other']:>7}  {row_total:>7}"
            )

        # --- Database record check ---
        self.stdout.write("")
        try:
            from webapp.models import IngestedDocument
            db_docs = list(IngestedDocument.objects.order_by("display_name"))
            if db_docs:
                self.stdout.write(f"  IngestedDocument DB records: {len(db_docs)}")
                for doc in db_docs:
                    in_store = doc.filename in sources
                    status = self.style.SUCCESS("[in store]") if in_store else self.style.ERROR("[NOT in store]")
                    self.stdout.write(f"    {status} {doc.display_name} ({doc.chunk_count} chunks registered)")
            else:
                self.stdout.write(self.style.WARNING(
                    "  No IngestedDocument records in database.\n"
                    "  Documents may have been ingested without registering."
                ))
        except Exception as exc:
            self.stdout.write(f"  Could not read IngestedDocument table: {exc}")

    # ------------------------------------------------------------------
    def _check_local(self):
        import os
        from pathlib import Path

        persist_dir     = getattr(settings, "CHROMA_PERSIST_DIR", None)
        base_dir        = Path(getattr(settings, "BASE_DIR", "."))
        persist_dir     = str(base_dir / (persist_dir or "chroma_db"))
        collection_name = getattr(settings, "CHROMA_COLLECTION", "pi_assist_docs")

        self.stdout.write(f"  CHROMA DIR : {persist_dir}")
        self.stdout.write(f"  COLLECTION : {collection_name}")
        self.stdout.write("")

        if not os.path.isdir(persist_dir):
            self.stdout.write(self.style.ERROR(
                f"  [FAIL] Chroma persist directory does not exist: {persist_dir}"
            ))
            return

        try:
            import chromadb
            from chromadb.utils import embedding_functions as ef
            client     = chromadb.PersistentClient(path=persist_dir)
            model_name = getattr(settings, "LOCAL_EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
            emb_fn     = ef.SentenceTransformerEmbeddingFunction(model_name=model_name)
            collection = client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
                embedding_function=emb_fn,
            )
            total = collection.count()
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  [FAIL] Could not open Chroma collection: {exc}"))
            return

        self.stdout.write(self.style.SUCCESS("  [OK] Local Chroma store is accessible."))
        self.stdout.write(f"\n  Total chunks : {total}")

        if total == 0:
            self.stdout.write(self.style.ERROR("  [EMPTY] Collection is empty — nothing has been ingested."))
            return

        result  = collection.get(limit=_PAGE_SIZE)
        all_metas = result.get("metadatas", []) or []

        sources = {}
        for meta in all_metas:
            src = (meta or {}).get("source", "UNKNOWN")
            ct  = (meta or {}).get("chunk_type", "other")
            if src not in sources:
                sources[src] = {"parent": 0, "child": 0, "other": 0}
            if ct == "parent":
                sources[src]["parent"] += 1
            elif ct == "child":
                sources[src]["child"] += 1
            else:
                sources[src]["other"] += 1

        self.stdout.write(f"  Documents    : {len(sources)}\n")
        self.stdout.write(f"  {'Source':<50} {'parent':>7} {'child':>7} {'other':>7}  {'total':>7}")
        self.stdout.write("  " + "-" * 76)
        for src, counts in sorted(sources.items()):
            row_total = sum(counts.values())
            self.stdout.write(
                f"  {src:<50} {counts['parent']:>7} {counts['child']:>7} "
                f"{counts['other']:>7}  {row_total:>7}"
            )
        if total > _PAGE_SIZE:
            self.stdout.write(f"\n  (showing first {_PAGE_SIZE} of {total} chunks)")
