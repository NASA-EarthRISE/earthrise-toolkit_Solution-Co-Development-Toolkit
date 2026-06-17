import os
import uuid
import json
import mimetypes

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import F
from django.http import JsonResponse, HttpResponseBadRequest, StreamingHttpResponse, FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils.encoding import smart_str
from django.conf import settings
from .models import NavSection, PageContent

from .openai_client import client, CHAT_MODEL
from .rag import build_context_snippets, get_store
from .prompts import SYSTEM_PROMPT
from .ingest_helpers import extract_text_and_chunk
from .document_registry import get_document_list_prompt
from .moderation import rate_limit, moderate_input, sanitize_document_chunks

UPLOAD_DIR = os.path.join(settings.BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
static_version = 1.0


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
        'static_version': static_version
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
def api_chat_upload(request):
    file = request.FILES.get("file")
    if not file:
        return JsonResponse({"error": "No file received"}, status=400)

    session_id = request.session.get("session_id")
    if not session_id:
        session_id = str(uuid.uuid4())
        request.session["session_id"] = session_id

    save_path = os.path.join(UPLOAD_DIR, f"{session_id}_{file.name}")

    with open(save_path, "wb") as f:
        for chunk in file.chunks():
            f.write(chunk)

    try:
        docs = extract_text_and_chunk(save_path)
        for d in docs:
            d["metadata"]["session_id"] = session_id
            d["metadata"]["is_global"] = False

        docs, redaction_warnings = sanitize_document_chunks(docs)

        store = get_store()
        store.upsert(docs)

        uploaded_files = request.session.get("uploaded_files", [])
        if file.name not in uploaded_files:
            uploaded_files.append(file.name)
        request.session["uploaded_files"] = uploaded_files
        request.session.modified = True

        response_data = {
            "message": f"File '{file.name}' ingested for this chat ({len(docs)} chunks).",
            "filename": file.name,
        }
        if redaction_warnings:
            response_data["warnings"] = redaction_warnings
        return JsonResponse(response_data)
    except Exception as e:
        return JsonResponse({"error": f"ERROR ingesting {file.name}: {e}"}, status=500)


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
    messages.append({"role": "system", "content": f"Context snippets:\n{context}" if context else "No retrieved context."})

    history = request.session.get("history", [])
    for h in history[-10:]:
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

    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": answer})
    request.session["history"] = history
    request.session.modified = True

    return JsonResponse({"reply": answer})


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
        return HttpResponseBadRequest(reason)

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
    messages.append({"role": "system", "content": f"Context snippets:\n{context}" if context else "No retrieved context."})
    messages.extend(history[-10:])
    messages.append({"role": "user", "content": user_text})

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
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": full})
            request.session["history"] = history
            request.session.modified = True

            yield _sse({"done": True, "full": full}, event="done")

        except Exception as e:
            yield _sse({"error": str(e)}, event="error")

    resp = StreamingHttpResponse(stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp

