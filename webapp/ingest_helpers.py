# pi_assist/ingest_helpers.py

import uuid
from pathlib import Path
import pandas as pd
from pypdf import PdfReader
from docx import Document
import docx2txt


def chunk_text(text, chunk_size=1800, overlap=300):
    """Split text into overlapping chunks. Fixed sliding-window logic."""
    chunks = []
    start = 0
    N = len(text)
    while start < N:
        end = min(start + chunk_size, N)
        chunks.append(text[start:end])
        if end == N:
            break
        start = end - overlap
    return chunks


def extract_docx(p: Path) -> str:
    # More robust than python-docx alone
    return docx2txt.process(str(p)) or ""


def extract_pdf_with_pages(p: Path) -> list:
    """Returns list of (page_text, page_num) tuples (1-indexed)."""
    reader = PdfReader(str(p))
    return [(pg.extract_text() or "", i + 1) for i, pg in enumerate(reader.pages)]


def extract_txt(p: Path) -> str:
    return Path(p).read_text(encoding="utf-8", errors="ignore")


def extract_excel(p: Path) -> str:
    dfs = pd.read_excel(p, sheet_name=None)
    return "\n\n".join(df.to_csv(index=False) for df in dfs.values())


def extract_text_and_chunk(filepath: str):
    p = Path(filepath)
    ext = p.suffix.lower()
    docs = []

    if ext == ".pdf":
        # Page-aware chunking: each chunk carries the page number it came from
        chunk_idx = 0
        for page_text, page_num in extract_pdf_with_pages(p):
            if not page_text.strip():
                continue
            for chunk in chunk_text(page_text):
                docs.append({
                    "id": f"{p.name}-{chunk_idx}-{uuid.uuid4().hex[:8]}",
                    "text": chunk,
                    "metadata": {
                        "source": p.name,
                        "path": str(p),
                        "page": page_num,
                        "chunk_idx": chunk_idx,
                    }
                })
                chunk_idx += 1
    else:
        if ext == ".docx":
            text = extract_docx(p)
        elif ext in [".txt", ".md"]:
            text = extract_txt(p)
        elif ext in [".xlsx", ".xls"]:
            text = extract_excel(p)
        else:
            raise ValueError(f"Unsupported type: {ext}")

        for i, chunk in enumerate(chunk_text(text)):
            docs.append({
                "id": f"{p.name}-{i}-{uuid.uuid4().hex[:8]}",
                "text": chunk,
                "metadata": {
                    "source": p.name,
                    "path": str(p),
                    "chunk_idx": i,
                }
            })

    return docs
