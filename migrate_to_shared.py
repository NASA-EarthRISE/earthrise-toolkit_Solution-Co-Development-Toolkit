# migrate_to_shared.py
# One-time script to migrate local ChromaDB data to the Shared Embedding Service.
# Run from the project root:
#   python migrate_to_shared.py
import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "solution_co_development_toolkit.settings")
django.setup()

import chromadb, requests
from pathlib import Path
from django.conf import settings

# Resolve persist dir the same way rag.py does
_user_dir = getattr(settings, "CHROMA_PERSIST_DIR", None)
_base_dir = Path(getattr(settings, "BASE_DIR", Path(__file__).resolve().parent))
LOCAL_DIR = Path(_user_dir) if _user_dir else (_base_dir / "chroma_db")
if not LOCAL_DIR.is_absolute():
    LOCAL_DIR = _base_dir / LOCAL_DIR
LOCAL_DIR = str(LOCAL_DIR)

COLLECTION_NAME  = settings.CHROMA_COLLECTION
SERVICE_URL      = settings.SHARED_EMBEDDING_SERVICE_URL
API_KEY          = settings.SHARED_EMBEDDING_SERVICE_API_KEY
HEADERS          = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
BATCH_SIZE       = 100

local_client = chromadb.PersistentClient(path=LOCAL_DIR)
col          = local_client.get_collection(COLLECTION_NAME)
total        = col.count()
offset       = 0

print(f"Migrating {total} documents from '{LOCAL_DIR}' to {SERVICE_URL} ...")

while offset < total:
    batch = col.get(
        limit=BATCH_SIZE,
        offset=offset,
        include=["documents", "metadatas"],
    )
    if not batch["ids"]:
        break

    resp = requests.put(
        f"{SERVICE_URL}/collections/{COLLECTION_NAME}/documents",
        json={
            "documents": batch["documents"],
            "ids":       batch["ids"],
            "metadatas": batch["metadatas"],
        },
        headers=HEADERS,
        timeout=120,
    )
    resp.raise_for_status()
    offset += len(batch["ids"])
    print(f"  {offset}/{total}")

print("Migration complete.")
