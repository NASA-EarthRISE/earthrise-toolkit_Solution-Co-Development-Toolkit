# pi_assist/ingest_helpers.py
"""
Document ingestion with hierarchical chunking and metadata enrichment.

Strategy (mirrors the high-quality RAG pipeline reference):
  1. Structural parsing  – detect section headings in PDFs; preserve page numbers.
  2. Hierarchical chunks – each section is split into large *parent* chunks
     (~2500 words) and smaller *child* chunks (~500 words, 100-word overlap).
  3. Metadata headers    – every child chunk is prefixed with
       "Document: <name>\\nSection: <section>\\nPage: <page>\\n\\n"
     so the LLM always knows the provenance of each passage.
  4. Parent stored too   – parent chunks are written to the vector store with
     chunk_type="parent" so retrieval can expand a child hit to fuller context.
"""

import re
import uuid
from pathlib import Path

import pandas as pd
from pypdf import PdfReader
import docx2txt

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SMALL_CHUNK_WORDS = 500
SMALL_CHUNK_OVERLAP_WORDS = 100

PARENT_CHUNK_WORDS = 2500
PARENT_CHUNK_OVERLAP_WORDS = 200

# Crude heading detector: ALL-CAPS lines of 4+ chars (same heuristic as the
# reference pipeline).  Tune with a stricter regex if false-positives appear.
_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9\s\-:]{3,}$")


# ---------------------------------------------------------------------------
# Low-level text utilities
# ---------------------------------------------------------------------------

def split_words(text: str, chunk_size: int, overlap: int) -> list:
    """Split *text* into overlapping word-based chunks."""
    words = text.split()
    if not words:
        return []
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += chunk_size - overlap
    return chunks


def _metadata_header(source: str, section: str, page) -> str:
    """Return a short provenance string to prepend to each child chunk."""
    parts = [f"Document: {source}"]
    if section:
        parts.append(f"Section: {section}")
    if page is not None:
        parts.append(f"Page: {page}")
    return "\n".join(parts) + "\n\n"


# ---------------------------------------------------------------------------
# File extractors
# ---------------------------------------------------------------------------

def extract_docx(p: Path) -> str:
    """More robust than python-docx alone."""
    return docx2txt.process(str(p)) or ""


def extract_pdf_with_sections(p: Path) -> list:
    """
    Extract text from a PDF, grouping lines by detected section headings.

    Returns a list of dicts: [{section, page, content}, ...].
    Falls back to one entry per page when no headings are detected.
    """
    reader = PdfReader(str(p))
    sections = []
    current_section = "Introduction"
    current_lines: list = []
    current_page = 1

    for page_idx, page in enumerate(reader.pages):
        page_num = page_idx + 1
        text = page.extract_text() or ""
        for line in text.splitlines():
            clean = line.strip()
            if not clean:
                continue
            if _HEADING_RE.match(clean):
                if current_lines:
                    sections.append({
                        "section": current_section,
                        "page": current_page,
                        "content": " ".join(current_lines),
                    })
                    current_lines = []
                current_section = clean
                current_page = page_num
            else:
                current_lines.append(clean)

    if current_lines:
        sections.append({
            "section": current_section,
            "page": current_page,
            "content": " ".join(current_lines),
        })

    return sections


def extract_pdf_with_pages(p: Path) -> list:
    """
    Fallback: returns [(page_text, page_num), ...] (1-indexed).
    Used when section detection yields no results.
    """
    reader = PdfReader(str(p))
    return [(pg.extract_text() or "", i + 1) for i, pg in enumerate(reader.pages)]


def extract_txt(p: Path) -> str:
    return Path(p).read_text(encoding="utf-8", errors="ignore")


def extract_excel(p: Path) -> str:
    dfs = pd.read_excel(p, sheet_name=None)
    return "\n\n".join(df.to_csv(index=False) for df in dfs.values())


# ---------------------------------------------------------------------------
# Hierarchical chunking
# ---------------------------------------------------------------------------

def _build_hierarchical_chunks(sections: list, source_name: str) -> list:
    """
    Convert a list of {section, page, content} dicts into a flat list of docs
    ready for upsert into the vector store.

    Each *section* is split into:
      • parent chunks (~2500 words) – stored with chunk_type="parent"
      • child  chunks (~500  words) – stored with chunk_type="child",
        a metadata header prepended, and a parent_id back-reference.

    Parent chunk IDs follow the pattern: "<source>-parent-<parent_uuid>"
    This lets build_context_snippets reconstruct the ID from metadata alone.
    """
    docs = []
    chunk_idx = 0

    for sec in sections:
        section = sec.get("section", "")
        page = sec.get("page")
        content = sec.get("content", "")
        if not content.strip():
            continue

        parent_texts = split_words(content, PARENT_CHUNK_WORDS, PARENT_CHUNK_OVERLAP_WORDS)

        for parent_text in parent_texts:
            parent_uuid = str(uuid.uuid4())
            parent_doc_id = f"{source_name}-parent-{parent_uuid}"

            # --- parent chunk (large context, stored but not used for retrieval directly) ---
            parent_meta = {
                "source": source_name,
                "section": section,
                "parent_id": parent_uuid,
                "chunk_type": "parent",
            }
            if page is not None:
                parent_meta["page"] = page

            docs.append({
                "id": parent_doc_id,
                "text": parent_text,
                "metadata": parent_meta,
            })

            # --- child chunks (small, enriched, embedded and retrieved) ---
            for child_text in split_words(parent_text, SMALL_CHUNK_WORDS, SMALL_CHUNK_OVERLAP_WORDS):
                header = _metadata_header(source_name, section, page)
                child_meta = {
                    "source": source_name,
                    "section": section,
                    "chunk_idx": chunk_idx,
                    "parent_id": parent_uuid,
                    "chunk_type": "child",
                }
                if page is not None:
                    child_meta["page"] = page

                docs.append({
                    "id": f"{source_name}-{chunk_idx}-{uuid.uuid4().hex[:8]}",
                    "text": header + child_text,
                    "metadata": child_meta,
                })
                chunk_idx += 1

    return docs


def _parse_affiliation_map(text: str) -> dict:
    """
    Parse the pipe-separated numbered affiliation block that appears below the
    author names in toolkit PDFs, e.g.:

        "1  EarthRISE Project Office, NASA MSFC |  2  Lab for Applied Sciences,
         University of Alabama in Huntsville |  3  NSITE ..."

    Returns {1: "EarthRISE Project Office, NASA MSFC", 2: "Lab for ...", ...}.
    Returns an empty dict when no such block is found.
    """
    # The block starts on a line that begins with "1 " (possibly preceded by
    # whitespace or a newline) and ends before Acknowledgments, Abstract, or
    # the end of the string.  Use (?:^|\n) so the match works whether or not
    # the first affiliation starts at the very beginning of a line in the
    # extracted text.
    block_match = re.search(
        r'(?:^|\n)\s*1\s+(.+?)(?=\n\s*Acknowledgments|\n\s*Abstract|\n\s*Introduction|\Z)',
        text,
        re.DOTALL | re.MULTILINE,
    )
    if not block_match:
        return {}

    block = "1 " + block_match.group(1)
    affil_map = {}
    for entry in block.split('|'):
        entry = entry.strip()
        m = re.match(r'^(\d+)\s+(.+)$', entry, re.DOTALL)
        if m:
            num = int(m.group(1))
            name = ' '.join(m.group(2).split())   # collapse internal whitespace
            affil_map[num] = name

    print(f"[DEBUG] Parsed {len(affil_map)} affiliations: {affil_map}")
    return affil_map


def extract_and_enhance_authors(text: str, source: str) -> dict:
    """
    Extract author information from document text and create a natural language
    chunk that will embed better for semantic search.

    Parses the numbered affiliation block (e.g. "1 EarthRISE ... | 2 Lab for ...")
    and maps each author to their specific affiliations via the superscript numbers
    that appear after their name in the PDF.
    """
    # Locate the author section — capture everything up to the affiliation block
    # or a major document section heading.
    # The lookahead detects the start of ANY numbered affiliation block (a line
    # beginning with "1 " followed by an uppercase word) rather than hardcoding
    # specific affiliation names that won't generalise across documents.
    author_section_pattern = (
        r'Authors?\s*[\n:]\s*(.*?)'
        r'(?=\n\s*1\s+[A-Z]|\n\s*Acknowledgments|\n\s*Abstract|\n\s*Introduction)'
    )

    match = re.search(author_section_pattern, text[:5000], re.MULTILINE | re.DOTALL)

    if not match:
        # Fallback: capture up to ~600 chars after "Authors" — allow multi-line
        # author blocks by not anchoring to a single line.
        author_section_pattern = r'Authors?\s*[\n:]\s*(.{50,600}?)(?=\n\n|\n\s*\d|\Z)'
        match = re.search(author_section_pattern, text[:5000], re.MULTILINE | re.DOTALL)

    if not match:
        return None

    authors_section = match.group(1)

    print(f"[DEBUG] Raw author section length: {len(authors_section)} chars")
    print(f"[DEBUG] Raw section (full): {repr(authors_section)}")

    # --- Step 1: Parse the numbered affiliation map from the full text ---
    affil_map = _parse_affiliation_map(text)

    # --- Step 2: Extract per-author affiliation numbers BEFORE stripping digits ---
    # Work on the whitespace-joined raw section so multi-line names are reunited.
    joined_raw = ' '.join(authors_section.split())
    author_affil_nums = {}   # {raw_name: [affil_num, ...]}
    if affil_map:
        for m in re.finditer(
            r'((?:[A-Z]\.\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+((?:\d+,)*\d+)',
            joined_raw,
        ):
            raw_name = m.group(1).strip()
            nums = [int(n) for n in m.group(2).split(',') if n.strip().isdigit()]
            if raw_name and nums:
                author_affil_nums[raw_name] = nums

    print(f"[DEBUG] Raw author->affil nums: {author_affil_nums}")

    # --- Step 3: Clean the author names (existing logic) ---
    authors_section_clean = ' '.join(authors_section.split())

    print(f"[DEBUG] After joining lines: {authors_section_clean}")

    # Remove all superscript numbers (affiliation markers)
    authors_section_clean = re.sub(r'\d+(?:,\d+)*', '', authors_section_clean)

    print(f"[DEBUG] After removing numbers: {authors_section_clean}")

    # Normalize spaces
    authors_section_clean = re.sub(r'\s+', ' ', authors_section_clean).strip()

    # Replace "&" with "," for consistent splitting
    authors_section_clean = authors_section_clean.replace(' & ', ', ')
    authors_section_clean = authors_section_clean.replace('&', ',')

    print(f"[DEBUG] After cleaning: {authors_section_clean}")

    # Split by commas
    author_parts = [p.strip() for p in authors_section_clean.split(',') if p.strip()]

    print(f"[DEBUG] Split into {len(author_parts)} parts: {author_parts}")

    # Filter to valid names
    # Pattern allows:
    # - FirstName LastName (e.g., "Diana West")
    # - Initial. FirstName LastName (e.g., "M. Kathleen Cutting")
    # - FirstName MiddleName LastName (e.g., "Emily Ann Smith")
    name_pattern = r'^(?:[A-Z]\.\s+)?[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+)+$'

    cleaned_names = []
    seen = set()

    for part in author_parts:
        # Clean any remaining punctuation except periods (for initials)
        part = re.sub(r'[^\w\s.]', '', part).strip()

        # Skip if too short or already seen
        if len(part) < 3 or part in seen:
            print(f"[DEBUG] SKIP: '{part}' (too short or duplicate)")
            continue

        # Check if it matches name pattern
        if re.match(name_pattern, part):
            seen.add(part)
            cleaned_names.append(part)
            print(f"[DEBUG] OK: '{part}'")
        else:
            print(f"[DEBUG] REJECT: '{part}' (doesn't match pattern)")

    if not cleaned_names:
        return None

    print(f"[EXTRACT] Found {len(cleaned_names)} authors in {source}: {cleaned_names}")

    # --- Step 4: Map each cleaned name to its affiliation names ---
    per_author_affils = {}   # {cleaned_name: ["Affil A", "Affil B"]}
    for name in cleaned_names:
        nums = author_affil_nums.get(name)
        if not nums:
            # Fallback: match by last name token
            last = name.rsplit(' ', 1)[-1]
            for raw_name, raw_nums in author_affil_nums.items():
                if raw_name.endswith(last):
                    nums = raw_nums
                    break
        if nums:
            affil_names = [affil_map[n] for n in nums if n in affil_map]
            if affil_names:
                per_author_affils[name] = affil_names

    # Flat unique list of all affiliations mentioned (for backwards compat)
    all_affils_unique = list(dict.fromkeys(
        a for affils in per_author_affils.values() for a in affils
    ))

    # Extract document title if present
    title_pattern = r'^([A-Z][^\n]{10,100})\n'
    title_match = re.search(title_pattern, text[:500], re.MULTILINE)
    doc_title = title_match.group(1).strip() if title_match else source

    # Create author name string with proper formatting
    if len(cleaned_names) == 1:
        author_string = cleaned_names[0]
    elif len(cleaned_names) == 2:
        author_string = f"{cleaned_names[0]} and {cleaned_names[1]}"
    else:
        author_string = ", ".join(cleaned_names[:-1]) + f", and {cleaned_names[-1]}"

    # --- Step 5: Build chunks ---
    # Scalar string for metadata — "Name: Affil A, Affil B; Name2: Affil C"
    affiliations_text = "; ".join(
        f"{name}: {', '.join(affils)}"
        for name, affils in per_author_affils.items()
    )

    base_metadata = {
        "source": source,
        "page": 1,
        "chunk_idx": -1,
        "is_metadata": True,
        "section": "authors",
        "author_count": len(cleaned_names),
        "authors": ", ".join(cleaned_names),
        "lead_author": cleaned_names[0],
        "document_title": doc_title,
        "affiliations_text": affiliations_text,
    }

    chunks = []

    # --- Overview chunk: who wrote it, full author+affiliation list ---
    overview_parts = [
        f"=== DOCUMENT AUTHORS: {source} ===",
        f"Document: {source}. The authors of this document are: {author_string}.",
        f"This toolkit document was written by: {author_string}.",
        f"Who wrote this document? This document was written by {author_string}.",
        f"Who are the authors of the toolkit? The toolkit authors are: {author_string}.",
        f"Who created this toolkit? The toolkit was created by: {author_string}.",
        f"This document has {len(cleaned_names)} authors: {author_string}.",
        (
            f"Lead author: {cleaned_names[0]}. Co-authors include: {', '.join(cleaned_names[1:])}."
            if len(cleaned_names) > 1 else f"Author: {cleaned_names[0]}."
        ),
        "The complete author list is:\n" + "\n".join(f"  {name}" for name in cleaned_names),
    ]

    if all_affils_unique:
        overview_parts.append(
            f"The authors are affiliated with: {', '.join(all_affils_unique)}."
        )

    if per_author_affils:
        affil_lines = "\n".join(
            f"  {name}: {', '.join(affils)}"
            for name, affils in per_author_affils.items()
        )
        overview_parts.append(f"Author affiliations for {source}:\n{affil_lines}")

    overview_parts += ["", "Raw author section from document:", authors_section[:500]]

    chunks.append({
        "id": f"{source}-authors-overview-{uuid.uuid4().hex[:8]}",
        "text": "\n\n".join(overview_parts),
        "metadata": {**base_metadata, "section": "authors-overview"},
    })

    # --- Per-author affiliation chunks (one per author with known affiliation) ---
    # Each gets its own embedding so person-specific queries ("What is X's affiliation?")
    # match tightly rather than being diluted by the full author list.
    for name, affils in per_author_affils.items():
        affil_str = ", ".join(affils)
        per_author_text = "\n".join([
            f"What is {name}'s affiliation? {name} is affiliated with: {affil_str}.",
            f"Where does {name} work? {name} works at: {affil_str}.",
            f"{name} is from: {affil_str}.",
            f"{name} affiliation: {affil_str}.",
        ])
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        chunks.append({
            "id": f"{source}-author-{slug}-{uuid.uuid4().hex[:8]}",
            "text": per_author_text,
            "metadata": {**base_metadata, "section": f"author-affiliation"},
        })

    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_text_and_chunk(filepath: str) -> list:
    """
    Extract text from *filepath* and return a list of chunk dicts ready for
    upsert:  [{id, text, metadata}, ...]

    PDFs go through section-aware hierarchical chunking.
    All other formats are treated as a single section.

    For every file type, author information is extracted from the opening
    text and, when found, prepended as a dedicated author chunk so that
    "who wrote this?" queries always find a high-quality answer.
    """
    p = Path(filepath)
    ext = p.suffix.lower()

    if ext == ".pdf":
        # Collect raw page text first — preserves newlines needed by the
        # author-extraction regex.  Section content has newlines stripped.
        raw_pages = extract_pdf_with_pages(p)   # [(text, page_num), ...]

        sections = extract_pdf_with_sections(p)
        if not sections:
            # Fallback: one entry per page
            sections = [
                {"section": "", "page": page_num, "content": text}
                for text, page_num in raw_pages
                if text.strip()
            ]

        docs = _build_hierarchical_chunks(sections, p.name)

        # Append path to every chunk so callers can locate the source file
        for doc in docs:
            doc["metadata"]["path"] = str(p)

        # Author extraction: use raw page text (newlines intact) from the
        # first 3 pages — identical to the sample approach.
        early_pages = [text for text, _ in raw_pages[:3] if text.strip()]
        if early_pages:
            early_text = "\n\n".join(early_pages)
            author_chunks = extract_and_enhance_authors(early_text, p.name)
            if author_chunks:
                for ac in author_chunks:
                    ac["metadata"]["path"] = str(p)
                docs[0:0] = author_chunks
                print(f"[INGEST] Extracted {author_chunks[0]['metadata']['author_count']} authors from {p.name} ({len(author_chunks)} author chunks)")

        return docs

    # Non-PDF: treat entire document as one section
    if ext == ".docx":
        text = extract_docx(p)
    elif ext in (".txt", ".md"):
        text = extract_txt(p)
    elif ext in (".xlsx", ".xls"):
        text = extract_excel(p)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    # Try author extraction before building hierarchical chunks
    author_chunks = extract_and_enhance_authors(text[:3000], p.name)

    sections = [{"section": "", "page": None, "content": text}]
    docs = _build_hierarchical_chunks(sections, p.name)

    # Append path to every chunk
    for doc in docs:
        doc["metadata"]["path"] = str(p)

    if author_chunks:
        for ac in author_chunks:
            ac["metadata"]["path"] = str(p)
        docs[0:0] = author_chunks
        print(f"[INGEST] Extracted {author_chunks[0]['metadata']['author_count']} authors from {p.name} ({len(author_chunks)} author chunks)")

    return docs
