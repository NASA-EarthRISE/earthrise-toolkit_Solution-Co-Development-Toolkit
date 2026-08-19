import logging
import os
import uuid
import json
import mimetypes

LOG = logging.getLogger(__name__)

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import F
from django.http import JsonResponse, HttpResponseBadRequest, StreamingHttpResponse, FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.encoding import smart_str
from django.conf import settings
from .models import NavSection, PageContent, VisitorFeedback, ChatPrompt, IngestedDocument

from .openai_client import client, CHAT_MODEL
from .rag import build_context_snippets, get_store
from .prompts import SYSTEM_PROMPT, build_context_message
from .document_registry import get_document_list_prompt
from .moderation import rate_limit, moderate_input, moderate_output, sanitize_history

UPLOAD_DIR = os.path.join(settings.BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
static_version = 1.4


def _nav():
    return NavSection.objects.all()


def _ctx(active_slug, request=None, extra=None):
    try:
        page_content = PageContent.objects.get(slug=active_slug)
        saved_content = page_content.html_content
    except PageContent.DoesNotExist:
        saved_content = None
    ctx = {
        'nav_sections': _nav(),
        'active_slug': active_slug,
        'saved_content': saved_content,
        'is_staff': request.user.is_staff if (request and request.user.is_authenticated) else False,
        'static_version': static_version,
        'chat_staff_only': getattr(settings, 'CHAT_STAFF_ONLY', False),
    }
    if extra:
        ctx.update(extra)
    return ctx


def home(request):
    return render(request, 'webapp/home.html', _ctx('home', request=request))


def introduction(request):
    return render(request, 'webapp/introduction.html', _ctx('introduction', request=request))


def designing_for_impact(request):
    return render(request, 'webapp/designing_for_impact.html', _ctx('designing-for-impact', request=request))


def capturing_communicating_impact(request):
    return render(request, 'webapp/capturing_communicating_impact.html', _ctx('capturing-communicating-impact', request=request))


def economic_impact_assessments(request):
    return render(request, 'webapp/economic_impact_assessments.html', _ctx('economic-impact-assessments', request=request))


def stakeholder_mapping(request):
    return render(request, 'webapp/stakeholder_mapping.html', _ctx('stakeholder-mapping', request=request))


def needs_assessment(request):
    return render(request, 'webapp/needs_assessment.html', _ctx('needs-assessment', request=request))


def information_chain_analysis(request):
    return render(request, 'webapp/information_chain_analysis.html', _ctx('information-chain-analysis', request=request))


def user_centered_design(request):
    return render(request, 'webapp/user_centered_design.html', _ctx('user-centered-design', request=request))


def technical_requirements(request):
    return render(request, 'webapp/technical_requirements.html', _ctx('technical-requirements', request=request))


def data_governance(request):
    return render(request, 'webapp/data_governance.html', _ctx('data-governance', request=request))


def implementation_monitoring(request):
    return render(request, 'webapp/implementation_monitoring.html', _ctx('implementation-monitoring', request=request))


def adoption_sustainability(request):
    return render(request, 'webapp/adoption_sustainability.html', _ctx('adoption-sustainability', request=request))


def meaningful_metrics(request):
    return render(request, 'webapp/meaningful_metrics.html', _ctx('meaningful-metrics', request=request))


def authors(request):
    return render(request, 'webapp/authors.html', _ctx('authors', request=request))


def trust_marker(request):
    return render(request, 'webapp/trust_marker.html', _ctx('trust-marker', request=request))


@require_POST
@staff_member_required
def save_page_content(request):
    try:
        data = json.loads(request.body)
        slug = data.get('slug', '').strip()
        html_content = data.get('html_content', '')
        if not slug:
            return JsonResponse({'error': 'slug required'}, status=400)
        PageContent.objects.update_or_create(
            slug=slug,
            defaults={'html_content': html_content, 'updated_by': request.user}
        )
        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def dynamic_page(request, slug):
    try:
        nav_section = NavSection.objects.get(slug=slug, is_dynamic=True)
    except NavSection.DoesNotExist:
        raise Http404
    is_staff = request.user.is_staff if (request and request.user.is_authenticated) else False
    if not nav_section.is_published and not is_staff:
        raise Http404
    ctx = _ctx(slug, request=request, extra={
        'nav_section': nav_section,
        'is_dynamic': True,
        'is_published': nav_section.is_published,
    })
    return render(request, 'webapp/dynamic_page.html', ctx)


@require_POST
@staff_member_required
def api_create_page(request):
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        slug = data.get('slug', '').strip()
        desc = data.get('desc', '').strip()
        insert_after_slug = data.get('insert_after_slug', '').strip()

        if not name or not slug:
            return JsonResponse({'error': 'name and slug are required'}, status=400)

        # Validate slug format
        import re as _re
        if not _re.match(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', slug):
            return JsonResponse({'error': 'Slug must be lowercase letters, numbers and hyphens only'}, status=400)

        if NavSection.objects.filter(slug=slug).exists():
            return JsonResponse({'error': f'Slug "{slug}" is already in use'}, status=400)

        # Determine insertion order
        if insert_after_slug:
            try:
                after = NavSection.objects.get(slug=insert_after_slug)
                new_order = after.order + 1
                # Shift existing sections up to make room
                NavSection.objects.filter(order__gte=new_order).update(order=F('order') + 1)
            except NavSection.DoesNotExist:
                new_order = (NavSection.objects.order_by('-order').values_list('order', flat=True).first() or 0) + 1
        else:
            new_order = (NavSection.objects.order_by('-order').values_list('order', flat=True).first() or 0) + 1

        NavSection.objects.create(
            name=name,
            slug=slug,
            desc=desc,
            url_name='',
            order=new_order,
            is_dynamic=True,
            is_published=False,
        )
        return JsonResponse({'ok': True, 'slug': slug, 'redirect_url': f'/tools/{slug}/'})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
@staff_member_required
def api_publish_page(request, slug):
    try:
        nav_section = NavSection.objects.get(slug=slug, is_dynamic=True)
    except NavSection.DoesNotExist:
        return JsonResponse({'error': 'Page not found'}, status=404)
    nav_section.is_published = True
    nav_section.save()
    return JsonResponse({'ok': True})


@require_POST
@staff_member_required
def api_delete_page(request, slug):
    try:
        nav_section = NavSection.objects.get(slug=slug, is_dynamic=True)
    except NavSection.DoesNotExist:
        return JsonResponse({'error': 'Page not found'}, status=404)
    PageContent.objects.filter(slug=slug).delete()
    nav_section.delete()
    return JsonResponse({'ok': True, 'redirect': '/'})


@csrf_exempt
@require_POST
def api_clear_chat(request):
    """
    Clear the server-side chat history and session-uploaded documents,
    then issue a fresh session_id so the next conversation starts clean.
    """
    old_session_id = request.session.get("session_id")

    # Remove session-specific RAG documents from the vector store
    if old_session_id:
        try:
            get_store().delete_session_docs(old_session_id)
        except Exception:
            pass  # best-effort — don't block the clear on store errors

    # Wipe conversation history and uploaded-file tracking
    request.session["history"] = []
    request.session["uploaded_files"] = []

    # Fresh session_id so future uploads are isolated from this new chat
    request.session["session_id"] = str(uuid.uuid4())
    request.session.cycle_key()  # rotate Django session key to prevent session fixation
    request.session.modified = True

    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
@rate_limit()
def api_message(request):
    try:
        raw = request.body.decode("utf-8") or "{}"
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    user_text = (payload.get("message") or "").strip()
    topic = (payload.get("topic") or "general").strip()

    if not user_text:
        return JsonResponse({"error": "Message is required"}, status=400)

    if len(user_text) > settings.MAX_MESSAGE_LENGTH:
        return JsonResponse(
            {"error": f"Message exceeds the {settings.MAX_MESSAGE_LENGTH}-character limit."},
            status=400,
        )

    safe, reason = moderate_input(user_text, client, CHAT_MODEL)
    if not safe:
        return JsonResponse({"error": reason}, status=400)

    session_id = request.session.get("session_id")

    try:
        context = build_context_snippets(user_text, top_k=15, session_id=session_id)
    except Exception:
        context = ""

    doc_list = get_document_list_prompt()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if doc_list:
        messages.append({"role": "system", "content": doc_list})
    messages.append({"role": "system", "content": build_context_message(context)})

    history = request.session.get("history", [])
    for h in sanitize_history(history[-10:]):
        messages.append(h)
    messages.append({"role": "user", "content": user_text})

    try:
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            temperature=0.2,
        )
        answer = resp.choices[0].message.content
    except Exception as e:
        return JsonResponse({"error": f"Chat backend error: {str(e)}"}, status=500)

    output_safe, _output_reason = moderate_output(answer)
    if not output_safe:
        LOG.warning("Blocked unsafe LLM output in api_message")
        return JsonResponse({"error": "I cannot provide that response."}, status=400)

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": answer})
    request.session["history"] = history
    request.session.modified = True

    prompt_id = None
    try:
        if not request.session.session_key:
            request.session.save()
        cp = ChatPrompt.objects.create(
            session_key=request.session.get("session_id") or request.session.session_key or '',
            prompt=user_text,
            response=answer,
            page_url=request.META.get('HTTP_REFERER', '')[:500],
        )
        prompt_id = cp.id
    except Exception:
        pass  # best-effort — never fail a chat over a DB write

    return JsonResponse({"reply": answer, "prompt_id": prompt_id})


def _sse(data: dict, event: str | None = None) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    if event:
        return f"event: {event}\ndata: {payload}\n\n"
    return f"data: {payload}\n\n"


@csrf_exempt
@rate_limit()
def api_message_stream(request):
    if request.method != "GET":
        return JsonResponse({"error": "Use GET with query params"}, status=405)

    user_text = smart_str(request.GET.get("message", "")).strip()
    topic = smart_str(request.GET.get("topic", "general")).strip()

    if not user_text:
        return HttpResponseBadRequest("message is required")

    if len(user_text) > settings.MAX_MESSAGE_LENGTH:
        return HttpResponseBadRequest(
            f"Message exceeds the {settings.MAX_MESSAGE_LENGTH}-character limit."
        )

    safe, reason = moderate_input(user_text, client, CHAT_MODEL)
    if not safe:
        def _blocked():
            yield _sse({"blocked": reason})
        resp = StreamingHttpResponse(_blocked(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        return resp

    session_id = request.session.get("session_id")

    try:
        context = build_context_snippets(user_text, top_k=20, session_id=session_id)
    except Exception:
        context = ""

    history = request.session.get("history", [])
    doc_list = get_document_list_prompt()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if doc_list:
        messages.append({"role": "system", "content": doc_list})
    messages.append({"role": "system", "content": build_context_message(context)})
    messages.extend(sanitize_history(history[-10:]))
    messages.append({"role": "user", "content": user_text})

    # Capture session identity before the generator runs.
    # Use the conversation UUID (session_id) so each "New Chat" gets a distinct
    # identifier in the review page, rather than the coarser Django cookie key.
    if not request.session.session_key:
        request.session.save()
    _session_key = request.session.get("session_id") or request.session.session_key or ''
    _page_url = request.META.get('HTTP_REFERER', '')[:500]

    def stream():
        yield _sse({"status": "starting"})

        collected = []
        try:
            resp = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,
                stream=True,
            )

            for chunk in resp:
                try:
                    delta = chunk.choices[0].delta if chunk.choices and chunk.choices[0].delta else None
                    finish_reason = chunk.choices[0].finish_reason if chunk.choices else None
                except Exception:
                    delta = None
                if delta and delta.content:
                    content = delta.content
                    collected.append(content)
                    yield _sse({"delta": content})

            full = "".join(collected)

            output_safe, _output_reason = moderate_output(full)
            if not output_safe:
                LOG.warning("Blocked unsafe LLM output in api_message_stream")
                yield _sse({"blocked": "I cannot provide that response."})
                return

            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": full})
            request.session["history"] = history
            # session.modified = True is not enough inside a StreamingHttpResponse
            # generator — the session middleware runs before the generator executes,
            # so we must save explicitly to persist history across requests.
            request.session.save()

            _prompt_id = None
            try:
                cp = ChatPrompt.objects.create(
                    session_key=_session_key,
                    prompt=user_text,
                    response=full,
                    page_url=_page_url,
                )
                _prompt_id = cp.id
            except Exception:
                pass  # best-effort

            yield _sse({"done": True, "full": full, "prompt_id": _prompt_id}, event="done")

        except Exception as e:
            yield _sse({"error": str(e)}, event="error")

    resp = StreamingHttpResponse(stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


# ---------------------------------------------------------------------------
# Visitor feedback submission (anonymous, no auth required)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def api_submit_feedback(request):
    """Accept anonymous qualitative feedback and issue reports from the chat widget."""
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    feedback_text = (data.get('feedback_text') or '').strip()
    if not feedback_text:
        return JsonResponse({'error': 'feedback_text is required'}, status=400)

    feedback_type = (data.get('feedback_type') or 'general').strip()
    valid_types = {t[0] for t in VisitorFeedback.FEEDBACK_TYPES}
    if feedback_type not in valid_types:
        feedback_type = 'general'

    raw_rating = data.get('rating')
    rating = None
    if raw_rating is not None:
        try:
            rating = int(raw_rating)
            if not 1 <= rating <= 5:
                rating = None
        except (ValueError, TypeError):
            rating = None

    page_url = (data.get('page_url') or '').strip()[:500]

    if not request.session.session_key:
        request.session.save()
    session_key = request.session.session_key or ''

    VisitorFeedback.objects.create(
        session_key=session_key,
        feedback_type=feedback_type,
        rating=rating,
        feedback_text=feedback_text,
        page_url=page_url,
    )
    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Per-response thumbs-up / thumbs-down feedback
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def api_response_feedback(request):
    """Record a thumbs-up or thumbs-down on a specific ChatPrompt, with optional comment."""
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    sentiment = (data.get('sentiment') or '').strip()
    if sentiment not in ('up', 'down'):
        return JsonResponse({'error': 'sentiment must be "up" or "down"'}, status=400)

    prompt_id = data.get('prompt_id')
    chat_prompt_obj = None
    if prompt_id is not None:
        try:
            chat_prompt_obj = ChatPrompt.objects.get(pk=int(prompt_id))
        except (ChatPrompt.DoesNotExist, ValueError, TypeError):
            pass  # store without FK if ID is unknown

    comment = (data.get('comment') or '').strip()[:2000]
    page_url = (data.get('page_url') or '').strip()[:500]

    if not request.session.session_key:
        request.session.save()
    session_key = request.session.session_key or ''

    VisitorFeedback.objects.create(
        session_key=session_key,
        feedback_type='chat_issue' if sentiment == 'down' else 'general',
        sentiment=sentiment,
        feedback_text=comment,
        page_url=page_url,
        chat_prompt=chat_prompt_obj,
    )
    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Staff review page — feedback results + prompt log
# ---------------------------------------------------------------------------

@staff_member_required
def review(request):
    """Staff-only page for reviewing visitor feedback and chat prompt logs."""
    from django.db.models import Avg, Count, Q, Prefetch

    # --- Feedback ---
    type_filter    = request.GET.get('type', '').strip()
    session_filter = request.GET.get('session', '').strip()
    feedback_qs = VisitorFeedback.objects.all()
    if type_filter:
        feedback_qs = feedback_qs.filter(feedback_type=type_filter)
    if session_filter:
        feedback_qs = feedback_qs.filter(session_key=session_filter)

    stats = {
        'total':      VisitorFeedback.objects.count(),
        'avg_rating': VisitorFeedback.objects.filter(rating__isnull=False)
                      .aggregate(avg=Avg('rating'))['avg'],
        'by_type':    {
            row['feedback_type']: row['cnt']
            for row in VisitorFeedback.objects
                         .values('feedback_type')
                         .annotate(cnt=Count('id'))
        },
    }

    # --- Prompts ---
    prompt_search = request.GET.get('q', '').strip()
    psort = request.GET.get('psort', 'date').strip()
    pdir  = request.GET.get('pdir',  'desc').strip()
    prompt_qs = ChatPrompt.objects.all()
    if prompt_search:
        prompt_qs = prompt_qs.filter(prompt__icontains=prompt_search)
    if session_filter:
        prompt_qs = prompt_qs.filter(session_key=session_filter)
    _order_map   = {'date': 'asked_at', 'session': 'session_key'}
    _order_field = _order_map.get(psort, 'asked_at')
    prompt_qs = prompt_qs.order_by(_order_field if pdir == 'asc' else f'-{_order_field}')

    prompt_qs = (
        prompt_qs
        .annotate(
            thumbs_up=Count(
                'response_feedback',
                filter=Q(response_feedback__sentiment='up'),
            ),
            thumbs_down=Count(
                'response_feedback',
                filter=Q(response_feedback__sentiment='down'),
            ),
        )
        .prefetch_related(
            Prefetch(
                'response_feedback',
                queryset=VisitorFeedback.objects.filter(
                    sentiment='down',
                ).exclude(feedback_text='').order_by('submitted_at'),
                to_attr='down_comments',
            )
        )
    )

    ctx = _ctx('review', request=request, extra={
        'feedback_list':  feedback_qs[:200],
        'stats':          stats,
        'feedback_types': VisitorFeedback.FEEDBACK_TYPES,
        'type_filter':    type_filter,
        'session_filter': session_filter,
        'prompt_list':    prompt_qs[:500],
        'prompt_search':  prompt_search,
        'psort':          psort,
        'pdir':           pdir,
    })
    return render(request, 'webapp/feedback_review.html', ctx)


# ---------------------------------------------------------------------------
# Document download — serves registered knowledge-base PDFs
# ---------------------------------------------------------------------------

def api_document_download(request, filename):
    """
    Serve a knowledge-base document for viewing/download.

    Security:
    - Filenames with path separators or '..' are rejected immediately.
    - The resolved absolute path must reside inside UPLOAD_DIR.
    - Files registered in IngestedDocument are preferred; unregistered files
      in UPLOAD_DIR (e.g. the combined toolkit PDF) are served as a fallback.
    """
    # Reject any path-traversal attempt before touching the filesystem
    if not filename or '/' in filename or '\\' in filename or '..' in filename:
        raise Http404

    uploads_dir = os.path.realpath(UPLOAD_DIR)

    # Prefer the database-registered path; fall back to uploads/ for files
    # that exist on disk but aren't individually chunked (e.g. the full PDF).
    try:
        doc = IngestedDocument.objects.get(filename=filename)
        candidate = os.path.realpath(doc.file_path)
    except IngestedDocument.DoesNotExist:
        candidate = os.path.realpath(os.path.join(UPLOAD_DIR, filename))

    # Belt-and-suspenders: confirmed path must be inside uploads/
    if not candidate.startswith(uploads_dir + os.sep):
        raise Http404

    if not os.path.isfile(candidate):
        raise Http404

    content_type, _ = mimetypes.guess_type(candidate)
    content_type = content_type or 'application/octet-stream'

    # PDFs can be displayed inline; DOCX and other formats must be downloaded
    as_attachment = not content_type == 'application/pdf'

    return FileResponse(
        open(candidate, 'rb'),
        content_type=content_type,
        as_attachment=as_attachment,
        filename=filename,
    )
