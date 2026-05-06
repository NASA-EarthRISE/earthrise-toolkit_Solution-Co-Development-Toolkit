# pi_assist/document_registry.py
"""
Helpers for registering and listing ingested global knowledge-base documents.
"""

from urllib.parse import quote


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
        from .models import IngestedDocument
        docs = IngestedDocument.objects.order_by("display_name")
        if not docs.exists():
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
        for doc in docs:
            url = f"/api/documents/{quote(doc.filename)}"
            lines.append(f"- [{doc.display_name}]({url}) ({doc.chunk_count} chunks)")

        return "\n".join(lines)

    except Exception:
        return ""
