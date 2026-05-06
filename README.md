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

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| Framework | Django 6.0.4 |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Frontend | Django Templates, vanilla CSS/JS |
| AI | OpenAI API (streaming chat completions) |
| RAG | Custom vector store (`webapp/rag.py`) |

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

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/stream?message=…` | Streaming SSE chat response |
| `POST` | `/api/message` | Non-streaming JSON chat response |
| `POST` | `/api/chat-upload` | Upload a file to session context |

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
SECRET_KEY=<django-secret-key>
DEBUG=True
```

### 5. Initialize the database
```bash
python manage.py migrate
```

### 6. Ingest toolkit documents *(optional)*
Upload PDFs/documents via the staff-only upload UI at `/upload`, or run the ingest management command if available.

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
│   ├── models.py                      # NavSection and document models
│   ├── openai_client.py               # OpenAI client wrapper
│   ├── rag.py                         # Vector store + retrieval
│   ├── prompts.py                     # System prompt templates
│   ├── document_registry.py           # Ingested document registry
│   ├── ingest_helpers.py              # Chunking / ingestion utilities
│   └── tests.py                       # Test suite
├── templates/
│   ├── base.html                      # Base layout, nav, chat widget
│   └── webapp/                        # Per-section content templates
├── static/
│   └── images/                        # NASA logo and hero image
├── uploads/                           # Session-scoped user file uploads
└── db.sqlite3                         # Local development database
```

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | API key for OpenAI chat completions |
| `SECRET_KEY` | Yes | Django secret key |
| `DEBUG` | No | `True` for development, `False` for production |

---

## License

**TODO:** Specify license. No LICENSE file present in repository.
