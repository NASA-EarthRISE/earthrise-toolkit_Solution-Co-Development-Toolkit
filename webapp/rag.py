# pi_assist/rag.py
"""
RAG utilities for the PI Assistant.

- Local mode: Chroma + sentence-transformers with persistent disk storage
- Proxy mode: LiteLLM-hosted RAG endpoints
"""

import os
import logging
from pathlib import Path
from typing import List, Dict, Any
import requests

from django.conf import settings

print(">>> USING rag.py FROM:", __file__)  # diagnostic

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

# Optional: suppress transformer noise
SUPPRESS_HF_WARNINGS = os.getenv("RAG_SUPPRESS_TRANSFORMER_WARNINGS", "true").lower() == "true"
if SUPPRESS_HF_WARNINGS:
    try:
        from transformers import logging as hf_logging
        hf_logging.set_verbosity_error()
    except Exception:
        pass

# ---------- Resolve absolute persistence dir under project root ----------
def _resolve_persist_dir() -> str:
    user_dir = getattr(settings, "CHROMA_PERSIST_DIR", None)
    base_dir = Path(getattr(settings, "BASE_DIR", Path(__file__).resolve().parents[1]))
    p = Path(user_dir) if user_dir else (base_dir / "chroma_db")
    if not p.is_absolute():
        p = base_dir / p
    return str(p)

CHROMA_PERSIST_DIR = _resolve_persist_dir()
CHROMA_COLLECTION  = getattr(settings, "CHROMA_COLLECTION", "pi_assist_docs")
DEFAULT_TOP_K      = 20

# Cosine distance threshold: chunks with distance >= this value are considered
# too dissimilar and are filtered out. (distance = 1 - cosine_similarity)
DISTANCE_THRESHOLD = 0.75

# ---------- Local embeddings ----------
def _build_local_embedding_function():
    from chromadb.utils import embedding_functions as ef
    # all-mpnet-base-v2 (768-dim) gives significantly better semantic matching
    # on technical domain text than the smaller all-MiniLM-L6-v2 (384-dim).
    # NOTE: changing this model invalidates any existing chroma_db — delete it
    # and re-run ingest before starting the server if you are upgrading.
    model_name = getattr(settings, "LOCAL_EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
    LOG.info(f"[RAG] Using local embedding model: {model_name}")
    return ef.SentenceTransformerEmbeddingFunction(model_name=model_name)

# ---------- Local Chroma store ----------
class ChromaVectorStore:
    """
    Local persistent vector store (Chroma) with local sentence-transformers embeddings.
    """
    def __init__(self):
        import chromadb
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
        # PersistentClient writes to disk and loads across processes
        self.chroma = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        self.embedding_function = _build_local_embedding_function()

        self.collection = self.chroma.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
            embedding_function=self.embedding_function,
        )

        try:
            count = self.collection.count()
            LOG.info(f"[RAG] Loaded Chroma collection '{CHROMA_COLLECTION}' from '{CHROMA_PERSIST_DIR}' with {count} records.")
        except Exception as e:
            LOG.warning(f"[RAG] Could not count collection: {e}")

    def upsert(self, docs: List[Dict[str, Any]]):
        """
        Upsert docs into the store. Each doc: {id, text, metadata}.
        Uses collection.upsert() so re-ingesting the same IDs updates rather
        than duplicating or raising DuplicateIDError.
        """
        if not docs:
            return
        ids       = [d["id"] for d in docs]
        texts     = [d["text"] for d in docs]
        metadatas = [d.get("metadata", {}) for d in docs]

        self.collection.upsert(ids=ids, documents=texts, metadatas=metadatas)
        LOG.info(f"[RAG] Upserted {len(docs)} doc chunks into '{CHROMA_COLLECTION}'.")

    def search(self, query: str, top_k: int = DEFAULT_TOP_K, session_id: str = None):
        """
        Query the store. Returns normalized list of results.
        If session_id is provided, includes both global docs and session-specific docs.
        """
        where = None
        if session_id:
            where = {
                "$or": [
                    {"session_id": session_id},
                    {"is_global": True}
                ]
            }
        else:
            where = {"is_global": True}

        res = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where if where else None
        )
        results = []
        if not res or not res.get("ids"):
            return results

        ids       = res.get("ids", [[]])[0]
        docs      = res.get("documents", [[]])[0]
        metadatas = res.get("metadatas", [[]])[0]
        distances = res.get("distances", [[]])[0] if "distances" in res else [None] * len(ids)

        for i in range(len(ids)):
            results.append({
                "id": ids[i],
                "text": docs[i],
                "metadata": metadatas[i],
                "distance": distances[i],
            })

        LOG.info(f"[RAG] Search (session={session_id}) returned {len(results)} result(s) for query='{query[:80]}...'")
        return results

    def delete_session_docs(self, session_id: str):
        """Delete all chunks associated with a specific session."""
        if not session_id:
            return
        try:
            self.collection.delete(where={"session_id": session_id})
            LOG.info(f"[RAG] Deleted docs for session {session_id}")
        except Exception as e:
            LOG.error(f"[RAG] Error deleting session docs: {e}")

# ---------- Proxy (LiteLLM RAG) ----------
class LiteLLMRagClient:
    def __init__(self):
        base = (settings.OPENAI_BASE_URL or "").rstrip("/")
        self.base = base
        self.search_path = getattr(settings, "LITELLM_RAG_SEARCH", "/rag/search")
        self.upsert_path = getattr(settings, "LITELLM_RAG_UPSERT", "/rag/upsert")
        self.api_key = settings.OPENAI_API_KEY
        if not self.base:
            raise RuntimeError("LiteLLM base_url is not set; check OPENAI_BASE_URL.")
        LOG.info(f"[RAG] Proxy RAG base: {self.base}")

    def upsert(self, docs: List[Dict[str, Any]]):
        url = f"{self.base}{self.upsert_path}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = requests.post(url, json={"docs": docs}, headers=headers, timeout=60)
        resp.raise_for_status()
        LOG.info(f"[RAG] Proxy upsert: {len(docs)} docs.")
        return resp.json()

    def search(self, query: str, top_k: int = DEFAULT_TOP_K, session_id: str = None):
        url = f"{self.base}{self.search_path}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"query": query, "top_k": top_k, "session_id": session_id}
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        LOG.info(f"[RAG] Proxy search returned {len(results)} result(s).")
        return results

# ---------- Shared Embedding Service store ----------
class SharedEmbeddingServiceStore:
    """
    Drop-in replacement for ChromaVectorStore that delegates embedding
    generation and vector storage to the Shared Embedding Service.

    The public interface is identical: upsert / search / delete_session_docs.
    """

    def __init__(self):
        self.base = (
            getattr(settings, "SHARED_EMBEDDING_SERVICE_URL", "http://localhost:8000")
        ).rstrip("/")
        self.api_key = getattr(settings, "SHARED_EMBEDDING_SERVICE_API_KEY", "")
        self.collection = getattr(settings, "CHROMA_COLLECTION", "pi_assist_docs")
        self._headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        LOG.info(
            f"[RAG] Shared Embedding Service: {self.base}  "
            f"collection: {self.collection}"
        )

    def upsert(self, docs: List[Dict[str, Any]]):
        if not docs:
            return
        payload = {
            "documents": [d["text"] for d in docs],
            "ids":       [d["id"]   for d in docs],
            "metadatas": [d.get("metadata", {}) for d in docs],
        }
        resp = requests.put(
            f"{self.base}/collections/{self.collection}/documents",
            json=payload,
            headers=self._headers,
            timeout=120,
        )
        resp.raise_for_status()
        LOG.info(f"[RAG] Upserted {len(docs)} doc chunks via shared service.")

    def search(
        self, query: str, top_k: int = DEFAULT_TOP_K, session_id: str = None
    ) -> List[Dict[str, Any]]:
        where = None
        if session_id:
            where = {"$or": [{"session_id": session_id}, {"is_global": True}]}
        else:
            where = {"is_global": True}

        payload = {
            "query_texts": [query],
            "n_results": top_k,
            "where": where,
        }
        resp = requests.post(
            f"{self.base}/collections/{self.collection}/query",
            json=payload,
            headers=self._headers,
            timeout=30,
        )
        resp.raise_for_status()
        res = resp.json()

        ids       = res.get("ids",       [[]])[0]
        docs      = res.get("documents", [[]])[0]
        metadatas = res.get("metadatas", [[]])[0]
        distances = res.get("distances", [[]])[0] if "distances" in res else [None] * len(ids)

        results = [
            {"id": ids[i], "text": docs[i], "metadata": metadatas[i], "distance": distances[i]}
            for i in range(len(ids))
        ]
        LOG.info(
            f"[RAG] Shared-service search (session={session_id}) returned "
            f"{len(results)} result(s) for query='{query[:80]}...'"
        )
        return results

    def delete_session_docs(self, session_id: str):
        """
        Delete all chunks for a session.

        The service's DELETE endpoint takes explicit IDs, so we first fetch
        all documents for this collection and filter by session_id locally,
        then delete the matching IDs in one call.
        """
        if not session_id:
            return
        try:
            # Fetch all IDs + metadata (paginate if collection is large)
            resp = requests.get(
                f"{self.base}/collections/{self.collection}/documents",
                params={"limit": 1000},
                headers=self._headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            ids       = data.get("ids", [])
            metadatas = data.get("metadatas", [])

            to_delete = [
                doc_id
                for doc_id, meta in zip(ids, metadatas)
                if (meta or {}).get("session_id") == session_id
            ]

            if not to_delete:
                return

            del_resp = requests.delete(
                f"{self.base}/collections/{self.collection}/documents",
                json={"ids": to_delete},
                headers=self._headers,
                timeout=30,
            )
            del_resp.raise_for_status()
            LOG.info(
                f"[RAG] Deleted {len(to_delete)} session docs for session {session_id}"
            )
        except Exception as e:
            LOG.error(f"[RAG] Error deleting session docs via shared service: {e}")

# ---------- Singleton factory ----------
# One store instance per process — avoids reloading the embedding model on
# every request and prevents multiple PersistentClient handles to the same dir.
_store_instance = None

def get_store():
    global _store_instance
    if _store_instance is None:
        mode = (getattr(settings, "RAG_MODE", "local") or "local").lower()
        if mode == "proxy":
            _store_instance = LiteLLMRagClient()
        elif mode == "shared":
            _store_instance = SharedEmbeddingServiceStore()
        else:
            _store_instance = ChromaVectorStore()
    return _store_instance

# ---------- Build snippets for grounding ----------
def build_context_snippets(query: str, top_k: int = DEFAULT_TOP_K, session_id: str = None) -> str:
    """
    Retrieve relevant chunks via multi-query expansion then format them as
    attributed context snippets for the LLM system message.

    Multi-query: runs the raw query plus two domain-specific sub-queries so
    that questions spanning multiple framework topics (e.g. RL criteria AND
    transition templates) get adequate coverage from both document types.
    """
    store = get_store()

    sub_queries = [
        query,
        f"Readiness Level criteria: {query}",
        f"transition plan requirements: {query}",
    ]

    seen_ids: set = set()
    all_results: List[Dict] = []
    per_q = max(top_k // len(sub_queries), 5)

    for q in sub_queries:
        for r in store.search(q, top_k=per_q, session_id=session_id):
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                all_results.append(r)

    # Filter out chunks that are too dissimilar to any sub-query
    filtered = [r for r in all_results if (r.get("distance") or 0.0) < DISTANCE_THRESHOLD]
    if not filtered:
        # Fallback: if everything exceeds threshold, use all retrieved results
        # rather than returning nothing (avoids leaving LLM with zero context)
        filtered = all_results

    # Best matches first; limit to top_k overall
    filtered.sort(key=lambda x: x.get("distance") or 1.0)
    filtered = filtered[:top_k]

    lines = []
    for r in filtered:
        meta      = r.get("metadata", {})
        src       = meta.get("source", "doc")
        page      = meta.get("page")
        chunk_idx = meta.get("chunk_idx", "?")
        dist      = r.get("distance")
        score     = round(1.0 - dist, 2) if dist is not None else "?"

        page_info = f" | Page {page}" if page else ""
        header    = f"[Source: {src}{page_info} | Chunk: {chunk_idx} | Relevance: {score}]"
        lines.append(f"{header}\n{r.get('text', '')}")

    context = "\n\n---\n\n".join(lines)
    if not context:
        LOG.info("[RAG] No context snippets retrieved for the query.")
    return context

# ---------- Optional diagnostics ----------
def diag_info() -> dict:
    mode = (getattr(settings, "RAG_MODE", "local") or "local").lower()
    info = {
        "mode": mode,
        "persist_dir": CHROMA_PERSIST_DIR,
        "collection": CHROMA_COLLECTION,
        "exists_on_disk": os.path.isdir(CHROMA_PERSIST_DIR),
        "count": None,
    }
    try:
        store = get_store()
        if isinstance(store, ChromaVectorStore):
            info["count"] = store.collection.count()
        elif isinstance(store, SharedEmbeddingServiceStore):
            resp = requests.get(
                f"{store.base}/collections",
                headers=store._headers,
                timeout=10,
            )
            resp.raise_for_status()
            for col in resp.json():
                if col["name"] == store.collection:
                    info["count"] = col["count"]
                    break
    except Exception as e:
        info["error"] = str(e)
    return info
