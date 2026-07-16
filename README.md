# Solution Co-Development Toolkit

[![Python: 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![EarthRISE: Development](https://img.shields.io/badge/EarthRISE-Development-b50000?labelColor=191f4c)](https://appliedsciences.nasa.gov/what-we-do/capacity-building/develop)

## Overview

The **Solution Co-Development Toolkit** is a Django-based web application built for **NASA Earth Action — Marshall Space Flight Center**. It provides structured, evidence-based guidance for planning, conducting, and communicating collaborative Earth observation solutions — from needs assessment through sustained impact.

The toolkit is authored by the EarthRISE Project, NASA SPoRT Center, and NASA NSITE team, and is designed for NASA-affiliated scientists working on applied, co-developed Earth science solutions.

### Toolkit sections

| # | Section |
|---|---------|
| 1 | Designing for Impact |
| 2 | Stakeholder Mapping & Analysis |
| 3 | Needs Assessment |
| 4 | Information Chain Analysis |
| 5 | User-Centered Design |
| 6 | Technical Requirements |
| 7 | Data Governance & Storage |
| 8 | Implementation Monitoring |
| 9 | Adoption & Sustainability |
| 10 | Meaningful Metrics |
| 11 | Capturing & Communicating Impact |
| 12 | Economic Impact Assessments |

---

## Stack

| Layer | Technology                              |
|-------|-----------------------------------------|
| Language | Python 3.13                             |
| Framework | Django 6.04+                            |
| Database | SQLite (dev) / PostgreSQL (prod)        |
| Frontend | Django Templates, vanilla CSS/JS        |
| AI | OpenAI API (streaming chat completions) |
| RAG | Custom vector store (`webapp/rag.py`)   |

---

## Features

### AI Chat Assistant
A floating chat widget is available on every page, powered by OpenAI via a Retrieval-Augmented Generation (RAG) pipeline over toolkit content.

- **Floating action button** — fixed at bottom-right of the viewport; click to open/close
- **Streaming responses** — replies stream in token-by-token via Server-Sent Events (`GET /api/stream`)
- **Three window sizes** — small (default), medium (expand button), and fullscreen (fills content area)
- **Copy button** — appears on hover over any assistant reply; copies raw markdown to clipboard
- **Session persistence** — full conversation history and window state (open/closed, size, file attachment) are saved to `sessionStorage` and restored automatically when navigating between pages
- **File attachment** — users can upload documents (PDF, DOCX, TXT, CSV, XLSX) scoped to their session for context-aware Q&A (`POST /api/chat-upload`)

### Responsive layout
- **Wide viewports (≥ 1500 px):** main content is constrained to 1200 px and centered in the space between the sidebar and the right edge of the viewport
- **Standard viewports:** fluid layout with a 280 px fixed sidebar
- **Mobile (≤ 768 px):** sidebar collapses behind a hamburger menu; main content fills full width

### RAG pipeline
Document chunks are stored in a custom vector store (`webapp/rag.py`). On each chat request, the top-15 most relevant snippets are retrieved and injected into the system prompt alongside the conversation history (last 10 turns).

### Input moderation
Every chat message is validated before being sent to the model:
- **Rate limiting** — configurable request limit per session per time window (default: 20 requests / 60 s)
- **Length validation** — messages over the configured maximum are rejected (default: 2000 characters)
- **Prompt injection detection** — regex patterns screen for common injection attempts
- **Topic classification** — LLM-based check to keep responses on-topic
- **Unicode normalization** — homoglyph-based bypass attempts are neutralised before pattern matching

### Staff features
Staff members (Django `is_staff`) have access to additional functionality:
- **Content editing** — in-page TinyMCE WYSIWYG editor to update any section's HTML, saved via `/api/save-page-content`
- **Dynamic tool pages** — create, edit, publish, unpublish, and delete custom tool pages at `/tools/<slug>/`
- **Document upload** — upload knowledge-base files (PDF, DOCX, TXT, CSV, XLSX) via the `/upload` interface
- **Feedback review** — view all visitor feedback and chat history at `/review/`

### Visitor feedback
- **Page feedback** — anonymous visitors can submit general feedback, bug reports, or chat issue reports
- **Response ratings** — thumbs up / down rating on individual AI responses

---

## API endpoints

### Chat

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/stream?message=…` | Streaming SSE chat response |
| `POST` | `/api/message` | Non-streaming JSON chat response |
| `POST` | `/api/clear-chat` | Clear session chat history |
| `POST` | `/api/chat-upload` | Upload a file to session context |

### Feedback

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/feedback` | Submit anonymous visitor feedback |
| `POST` | `/api/response-feedback` | Rate an AI response (thumbs up/down) |

### Staff only

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/save-page-content` | Save edited HTML content for a page |
| `POST` | `/api/create-page` | Create a new dynamic tool page |
| `POST` | `/api/publish-page/<slug>` | Publish or unpublish a tool page |
| `POST` | `/api/delete-page/<slug>` | Delete a tool page |
| `GET` | `/api/documents/<filename>` | Download a knowledge-base document |

---

## Setup

### 1. Clone the repository
```bash
git clone <repository-url>
cd "Solution Co-Development Toolkit"
```

### 2. Create a virtual environment
```bash
python -m venv venv
# Windows:
.\venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables
Create a `.env` file (or export directly) with:
```env
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://....
MODEL=gemini-2.5-pro
DJANGO_SECRET_KEY=<django-secret-key>
DJANGO_DEBUG=True
```

### 5. Initialize the database
```bash
python manage.py migrate
```

### 6. Ingest toolkit documents
Upload PDFs/documents via the staff-only upload UI at `/upload`. After uploading, verify the store with `rag_status` and recover from any gaps with `reingest_missing` (see [Management commands](#management-commands) below).

### 7. Run the development server
```bash
python manage.py runserver
```
The application is available at `http://127.0.0.1:8000/`.

---

## Common commands

```bash
python manage.py runserver       # Start dev server
python manage.py migrate         # Apply migrations
python manage.py makemigrations  # Create new migrations
python manage.py collectstatic   # Collect static files for production
python manage.py test webapp     # Run test suite
```

---

## Management commands

These commands manage the RAG vector store. Run them from the project root with your virtual environment active.

---

### `rag_status` — inspect the vector store

Reports the active RAG mode, service connectivity, and a full inventory of every document and chunk type in the current collection. Also cross-references `IngestedDocument` database records against what is actually in the store.

```bash
python manage.py rag_status
```

**Sample output**
```
============================================================
  RAG STATUS REPORT
============================================================
  RAG_MODE : shared
  SERVICE  : http://127.0.0.1:8023
  COLLECTION: pi_assist_docs

  [OK] Shared embedding service is reachable.
  [OK] Collection 'pi_assist_docs' exists.

  Total chunks : 412
  Documents    : 14

  Source                                             parent   child   other    total
  ----------------------------------------------------------------------------
  Needs Assessment.pdf                                   12      48       0       60
  Stakeholder Mapping & Analysis.pdf                     10      40       0       50
  ...

  IngestedDocument DB records: 14
    [in store] Needs Assessment (60 chunks registered)
    [in store] Stakeholder Mapping & Analysis (50 chunks registered)
    ...
============================================================
```

If a document shows `[NOT in store]`, use `reingest_missing` to fix it.

---

### `delete_document_chunks` — remove a document's chunks

Deletes all vector-store chunks for a specific document (matched by exact source filename) and removes the corresponding `IngestedDocument` database record. Optionally re-ingests the file immediately after deleting.

```bash
# Dry-run — show what would be deleted without making any changes
python manage.py delete_document_chunks "Needs Assessment.pdf" --dry-run

# Delete chunks and DB record
python manage.py delete_document_chunks "Needs Assessment.pdf"

# Delete then immediately re-ingest from uploads/
python manage.py delete_document_chunks "Needs Assessment.pdf" --reingest
```

| Flag | Description |
|------|-------------|
| `--dry-run` | List matching chunks but do not delete |
| `--reingest` | After deleting, re-ingest the file from `uploads/` |

> The filename must match exactly (including extension and capitalisation) as stored in chunk metadata.

---

### `reingest_missing` — reingest documents missing from the store

Compares every `IngestedDocument` database record against the current vector store and re-ingests any documents whose chunks are absent. This is the primary recovery command when switching RAG backends (e.g. migrating from local Chroma to the shared embedding service).

```bash
# Dry-run — show what would be reingested without making any changes
python manage.py reingest_missing --dry-run

# Reingest all missing documents
python manage.py reingest_missing

# Reingest missing documents AND delete orphan chunks
# (chunks in the store with no matching IngestedDocument record)
python manage.py reingest_missing --purge-orphans
```

| Flag | Description |
|------|-------------|
| `--dry-run` | Report what would happen without making any changes |
| `--purge-orphans` | Also delete chunks whose source filename has no `IngestedDocument` record (e.g. leaked session uploads) |

**Typical workflow after switching to the shared embedding service**

```bash
# 1. Check what is in the store vs the database
python manage.py rag_status

# 2. Preview what would be reingested
python manage.py reingest_missing --dry-run

# 3. Reingest and clean up any orphan chunks in one pass
python manage.py reingest_missing --purge-orphans
```

> Documents must exist in the `uploads/` directory. If a file is missing from `uploads/` the command will report it as skipped.

---

## Project structure

```text
.
├── manage.py
├── solution_co_development_toolkit/
│   ├── settings.py                    # Django settings
│   └── urls.py                        # Root URL routing
├── webapp/
│   ├── views.py                       # Page views + API endpoints
│   ├── views_upload.py                # Staff document upload
│   ├── urls.py                        # App URL routing
│   ├── models.py                      # NavSection, IngestedDocument, PageContent, VisitorFeedback, ChatPrompt
│   ├── admin.py                       # Django admin configuration
│   ├── apps.py                        # App configuration
│   ├── openai_client.py               # OpenAI client wrapper
│   ├── rag.py                         # Vector store + retrieval
│   ├── prompts.py                     # System prompt templates
│   ├── moderation.py                  # Input safety and rate limiting
│   ├── document_registry.py           # Ingested document registry
│   ├── ingest_helpers.py              # Chunking / ingestion utilities
│   ├── tests.py                       # Test suite
│   ├── static/
│   │   ├── css/
│   │   │   └── toolkit.css            # Main stylesheet
│   │   └── images/                    # NASA logo, hero image, and section figures
│   └── management/
│       └── commands/
│           ├── rag_status.py          # Inspect vector store contents
│           ├── delete_document_chunks.py  # Remove chunks for a document
│           └── reingest_missing.py    # Reingest DB docs absent from store
├── templates/
│   ├── base.html                      # Base layout, nav, chat widget
│   └── webapp/                        # Per-section content templates
├── uploads/                           # Session-scoped user file uploads
└── db.sqlite3                         # Local development database
```

---

## Environment variables

### Core

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DJANGO_SECRET_KEY` | Yes | `dev-secret` | Django secret key — use a long random value in production |
| `DJANGO_DEBUG` | No | `True` | `True` for development, `False` for production |
| `OPENAI_API_KEY` | Yes | — | API key passed to the LLM/embedding provider |
| `OPENAI_BASE_URL` | Yes | — | Base URL for chat completions (e.g. NASA LiteLLM proxy) |
| `MODEL` | No | `gpt-4o-mini` | Chat completion model name |
| `EMBEDDING_MODEL` | No | `text-embedding-3-large` | Embedding model name |

### RAG / vector store

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RAG_MODE` | No | `shared` | `shared` (shared embedding service), `local` (local Chroma), or `proxy` (LiteLLM RAG) |
| `SHARED_EMBEDDING_SERVICE_URL` | When `RAG_MODE=shared` | `http://localhost:8000` | Base URL of the shared embedding service |
| `SHARED_EMBEDDING_SERVICE_API_KEY` | When `RAG_MODE=shared` | _(empty)_ | API key for the shared embedding service |
| `CHROMA_COLLECTION` | No | `pi_assist_docs` | Name of the Chroma collection |
| `CHROMA_PERSIST_DIR` | No | `chroma_db` | Path (relative to `BASE_DIR`) for the local Chroma store |
| `LOCAL_EMBEDDING_MODEL` | No | `sentence-transformers/all-MiniLM-L6-v2` | Sentence-transformer model used when `RAG_MODE=local` |

### Deployment

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SCRIPT_NAME` | No | _(empty)_ | URL prefix for sub-path proxy deployments, e.g. `/earthrise-toolkit/solution-co-development-toolkit` — leave blank for local dev |
| `CSRF_TRUSTED_ORIGINS` | No | _(empty)_ | Comma-separated list of additional trusted origins, e.g. `https://science-dev.data.nasa.gov` |

### Feature flags

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CHAT_STAFF_ONLY` | No | `True` | `True` — AI chat widget shown to staff only; `False` — visible to all visitors |
| `MAX_MESSAGE_LENGTH` | No | `2000` | Maximum characters allowed in a single chat message |
| `RATE_LIMIT_CHAT_REQUESTS` | No | `20` | Maximum chat requests per rate-limit window per session |
| `RATE_LIMIT_CHAT_WINDOW_SECONDS` | No | `60` | Duration of the rate-limit window in seconds |

---

## License and Distribution

Solution-Co-Development-Toolkit is distributed by EarthRISE under the terms of the MIT License. See
[LICENSE](https://github.com/NASA-EarthRISE/Solution-Co-Development-Toolkit/blob/main/LICENSE) in this directory for more information.
