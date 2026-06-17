# AI Chatbot Compliance & Stakeholder Briefing

**Project:** NASA MSFC Earth Action — Solution Co-Development Toolkit
**Document purpose:** Pre-development consultation record and compliance evidence for OCOMM, Chief AI Officer, and Office of the CIO, per NASA web policy Section 5.14 "Use of AI Chatbots on NASA Webpages"
**Prepared by:** Solution Co-Development Toolkit team
**Date:** 2026-06-15
**Status:** For review and consultation

---

## 1. Overview

The NASA MSFC Solution Co-Development Toolkit is a web-based resource that guides Earth observation (EO) practitioners through a structured methodology for co-developing user-centered solutions. The toolkit contains multiple interconnected phases and tools covering needs assessment, stakeholder mapping, co-design, technical requirements, data governance, impact evaluation, and sustainability.

An AI-powered chat assistant has been integrated into the toolkit to help users navigate and apply this complex, multi-section resource. The assistant operates on a Retrieval-Augmented Generation (RAG) architecture, meaning it answers only from the toolkit's own ingested content — not from general-purpose internet knowledge.

This document responds to each consideration listed in Section 5.14.1 and documents the technical safeguards, content boundaries, and accessibility posture required for consultation with OCOMM, the Chief AI Officer, and the Office of the CIO.

---

## 2. Mandatory Consultation Record (Section 5.14)

Per Section 5.14, the Responsible NASA Official (RNO) for this website must consult with **OCOMM** before initiating development. This document is intended to initiate and support that consultation.

**Contacts to engage:**

| Office | Role | Trigger |
|--------|------|---------|
| OCOMM / OCOMM AI Working Group | Digital communications standards, UX, accessibility review | Required before development proceeds |
| Chief AI Officer | AI governance review | May be required depending on OCOMM referral |
| Office of the CIO (OCIO) | Security, ATO, GenAI policy alignment | Required for public deployment; ATO must be obtained |

**Applicable policies this deployment must comply with:**

- NID 2800.147 (NASA IT Security)
- NID 1383.155 (NASA Web and Digital Services)
- NASA Framework for the Ethical Use of AI
- OCIO GenAI Guidance (INT)

**Type of chatbot:** This is a generative AI chatbot (LLM-powered), not a response-bank chatbot. It generates responses using a large language model (LLM) grounded in retrieved toolkit content. This distinction is relevant to the level of review required per Section 5.14.

---

## 3. Section 5.14.1 — Pre-Development Considerations

### 3.1 Is the website visitor's need clearly defined?

Yes. The toolkit addresses a specific, well-bounded user need: practitioners engaged in Earth observation solution co-development need guided assistance navigating a structured, multi-phase methodology.

Identified user struggles:
- Locating the correct phase or tool for their current project stage
- Understanding how toolkit components relate to each other
- Applying abstract methodology steps to concrete scenarios
- Finding exact text, templates, or definitions within dense technical content

The chatbot directly addresses these: it retrieves relevant sections, synthesizes relationships between tools, provides step-by-step guidance, and returns verbatim text on request — all grounded in the toolkit itself.

### 3.2 Can the issue be addressed through simpler means?

The following non-AI alternatives were considered:

| Alternative | Assessment |
|-------------|------------|
| Improved navigation / page structure | Implemented. The site has a persistent nav sidebar and active-page highlighting. However, cross-phase synthesis requires reading multiple pages. |
| Plain-language rewriting | Implemented. Content was authored for accessibility. However, applying methodology to user-specific scenarios still requires interactive guidance. |
| Enhanced search / metadata | Beneficial but insufficient. Keyword search cannot synthesize relationships between toolkit phases or answer "how do I apply this to my project?" questions. |
| FAQs or decision trees | The toolkit's methodology is too situational for a fixed FAQ. Users arrive with unique project contexts. |

**Conclusion:** Static content improvements have been applied. The remaining unaddressed need — interactive, context-sensitive guidance across a multi-phase methodology — is well-suited to a RAG-grounded chatbot and is not adequately served by simpler means.

### 3.3 Will the chatbot be trained on well-bounded and factual content?

Yes. The chatbot does not use general internet knowledge. Its knowledge base consists exclusively of:

1. **Toolkit documents** — Staff-ingested documents (PDFs, DOCX, TXT, spreadsheets) that form the official toolkit content. These are managed by authorized staff via the Django admin interface and the document ingestion pipeline.
2. **Session-uploaded documents** — Users may optionally upload their own documents for a single chat session. These documents are isolated to that session and deleted when the session is cleared. They never enter the global knowledge base.

Content that is speculative, interpretive, or sensitive is excluded by design — no such content has been ingested into the toolkit knowledge base. The system prompt explicitly instructs the LLM not to introduce external frameworks, reinterpret toolkit intent, or speculate beyond provided material.

**Knowledge base management:** Document ingestion is restricted to authorized staff. The ingestion pipeline (`ingest_helpers.py`) supports PDF, DOCX, TXT, Markdown, and spreadsheet formats. Each document is chunked hierarchically, embedded, and stored in the vector database with source metadata preserved for attribution.

### 3.4 Will the chatbot have guardrails to prevent answering improper inputs or providing improper responses?

Yes. The following guardrails are implemented at multiple layers:

#### Input Guardrails

| Guardrail | Implementation | Detail |
|-----------|---------------|--------|
| Empty/blank input rejection | `views.py` API endpoints | Returns HTTP 400 before reaching the LLM |
| Malformed request rejection | `views.py` JSON parsing | Returns HTTP 400 on invalid JSON body |
| Input length limit | `views.py` length check | Messages exceeding 2,000 characters rejected with HTTP 400 before reaching the LLM |
| Rate limiting | `moderation.py` rate_limit decorator | Maximum 20 requests per minute per IP; returns HTTP 429 on breach; keyed per-endpoint using Django FileBasedCache |
| Prompt injection filter | `moderation.py` regex patterns | 13 prompt-injection and jailbreak patterns (e.g., "ignore previous instructions", "DAN", `<system>`) blocked before the RAG/LLM step |
| Off-topic message filter | `moderation.py` LLM classifier | Single low-cost LLM classification call rejects messages unrelated to the toolkit or Earth observation |
| RAG relevance threshold | `rag.py` distance filter | Chunks with cosine distance ≥ 0.75 are excluded; semantically unrelated content never reaches the LLM |
| Bounded conversation history | `views.py` history slice | Only the last 10 conversation turns are included in the LLM context |
| Session isolation | Session ID (UUID4) | Each user's uploaded documents are isolated to their session and cannot be accessed by other users |

#### Output Guardrails (Prompt-Level)

The system prompt enforces the following behavioral constraints on the LLM at every interaction:

| Constraint | Effect |
|------------|--------|
| Base all answers strictly on retrieved toolkit content | Prevents hallucination of content not in the toolkit |
| Do not invent or assume content | Prevents gap-filling with model priors |
| Do not introduce external frameworks, methods, or opinions | Keeps responses within toolkit scope |
| Do not speculate beyond provided material | Prevents interpretive overreach |
| Do not modify or reinterpret toolkit intent | Preserves fidelity to authored content |
| Low temperature (0.2) | Reduces response variance and hallucination risk |

#### Out-of-Scope Question Handling

When the retrieval system finds no relevant content, the LLM is instructed to respond:

> *"This information is not available in the toolkit."*

It may optionally suggest the closest relevant concept from the toolkit. It is explicitly prohibited from drawing on external knowledge to fill the gap.

#### Frontend Output Safety

All LLM-generated text is HTML-escaped before rendering in the browser, preventing any cross-site scripting (XSS) risk from generated content.

### 3.5 Malicious Attack Protection

The following protections are in place:

| Attack vector | Protection |
|---------------|------------|
| XSS via LLM output | `esc()` HTML encoding function applied to all rendered output |
| CSRF on state-changing operations | Django CSRF tokens required on admin/content operations |
| Prompt injection via user messages | Dedicated 13-pattern regex filter in `moderation.py` blocks injection attempts before the RAG/LLM step |
| Prompt injection via uploaded documents | `moderation.py` `sanitize_document_chunks()` scans all document chunks post-extraction and redacts matching patterns before vector store ingestion |
| Oversized / denial-of-service inputs | 2,000-character input length limit enforced in `views.py` on both chat endpoints |
| Endpoint abuse / cost overrun | Rate limiter (20 req/min/IP) enforced via `moderation.py` decorator on both chat endpoints |
| Off-topic or adversarial prompts | LLM topic classifier in `moderation.py` rejects messages unrelated to the toolkit before any RAG or generation call |
| Session data leakage | UUID4 session IDs; session-specific documents isolated and cleared on session reset |

All previously identified gaps have been remediated. There are no outstanding known gaps.

---

## 4. Accessibility Compliance

The toolkit has been tested against **WCAG 2.0 Level A and AA** (which Section 508 revised 2018 incorporates by reference). Automated testing with **pa11y v8** across all 16 pages returns **0 issues**.

The AI chat widget specifically includes:
- ARIA labels and roles on all interactive elements
- Keyboard navigation support (full tab order, Escape to close)
- Focus trapping within the chat modal
- Sufficient color contrast on all chat UI elements
- Screen reader-compatible message rendering

Full accessibility compliance details are documented in `compliance.md`.

---

## 5. Infrastructure and Security Posture

| Item | Detail |
|------|--------|
| LLM routing | All LLM calls route through NASA's internal LiteLLM proxy (`llm-api-access.caio.mcp.nasa.gov`), not directly to a commercial API |
| Authentication to LLM | LiteLLM proxy token (not end-user credentials) stored in server environment variables |
| Vector database | Shared Embedding Service at `http://127.0.0.1:8023` (internal/localhost) |
| No user PII transmitted to LLM | User messages are conversational toolkit queries; no PII collection is prompted or required |
| Conversation history | Stored server-side in Django sessions only; not persisted to a database; cleared on session reset |
| File uploads | Stored temporarily in server `uploads/` directory; isolated per session; removed on session clear |
| Web framework | Django 4.2+ with standard security middleware (CSRF, clickjacking protection, secure headers) |

**Authority to Operate (ATO):** An ATO has not yet been obtained. This is a required step before public deployment per Section 5.14. Engagement with OCIO security review should be initiated in parallel with OCOMM consultation.

---

## 6. Content Optimization for Third-Party LLMs (Section 5.14.2)

Section 5.14 recommends preparing content for ingestion by third-party chatbot tools as an alternative to deploying a NASA-specific one. As a parallel measure, the toolkit's content structure supports this:

- All toolkit pages use semantic HTML with clear heading hierarchy
- Page content is authored in plain language
- Metadata (page titles, section headings, descriptions) is structured for search engine discoverability
- Content is not behind authentication walls

This means the toolkit content is already well-positioned for ingestion by third-party LLM tools (e.g., search engine AI overviews, enterprise knowledge bases) independent of the custom chatbot.

---

## 7. Recommended Next Steps

The following actions are needed to reach compliance for public deployment:

1. **Initiate OCOMM consultation** — Submit this document to the OCOMM AI Working Group to begin the formal review process.
2. **Determine Chief AI Officer review requirement** — OCOMM will advise whether escalation to the Chief AI Officer is needed.
3. **Initiate ATO process with OCIO** — Begin security review and Authority to Operate application. Provide infrastructure summary from Section 5 of this document.
4. **Policy alignment check** — Confirm compliance with NID 2800.147, NID 1383.155, NASA Framework for Ethical Use of AI, and OCIO GenAI Guidance against this document.

---

## 8. Supporting Documentation

| Document | Location | Purpose |
|----------|----------|---------|
| Accessibility compliance report | `compliance.md` | WCAG 2.0 A/AA and Section 508 test results |
| System prompt | `webapp/prompts.py` | Full behavioral constraints on the LLM |
| RAG implementation | `webapp/rag.py` | Vector search, relevance filtering, session isolation |
| Chat API views | `webapp/views.py` | Input validation, length limits, moderation calls, message handling, streaming |
| Input safety controls | `webapp/moderation.py` | Rate limiting, injection patterns, topic classifier, document sanitizer |
| Document ingestion | `webapp/ingest_helpers.py` | Knowledge base content pipeline |
| Django settings | `solution_co_development_toolkit/settings.py` | Infrastructure and safety configuration |
