import os
import uuid
import json
import mimetypes

from django.contrib.admin.views.decorators import staff_member_required
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

UPLOAD_DIR = os.path.join(settings.BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


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

        store = get_store()
        store.upsert(docs)

        uploaded_files = request.session.get("uploaded_files", [])
        if file.name not in uploaded_files:
            uploaded_files.append(file.name)
        request.session["uploaded_files"] = uploaded_files
        request.session.modified = True

        return JsonResponse({
            "message": f"File '{file.name}' ingested for this chat ({len(docs)} chunks).",
            "filename": file.name
        })
    except Exception as e:
        return JsonResponse({"error": f"ERROR ingesting {file.name}: {e}"}, status=500)


@csrf_exempt
@require_POST
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
def api_message_stream(request):
    if request.method != "GET":
        return JsonResponse({"error": "Use GET with query params"}, status=405)

    user_text = smart_str(request.GET.get("message", "")).strip()
    topic = smart_str(request.GET.get("topic", "general")).strip()

    if not user_text:
        return HttpResponseBadRequest("message is required")

    session_id = request.session.get("session_id")

    try:
        context = build_context_snippets(user_text, top_k=15, session_id=session_id)
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

