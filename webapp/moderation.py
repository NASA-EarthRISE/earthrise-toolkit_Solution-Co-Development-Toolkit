"""
moderation.py — Input safety controls for the AI chat assistant.

Provides:
  rate_limit        — decorator that enforces per-IP request rate limits
  moderate_input    — two-phase check: regex injection patterns + LLM topic classifier
  sanitize_document_chunks — scans uploaded document chunks for embedded injection

Conspiracy / misinformation categories filtered in Phase 1b (regex, no API call):
  flat_earth, hollow_earth, climate_denial, moon_landing_hoax, chemtrails, space_denial
"""

import re
import logging
import functools

from django.core.cache import cache
from django.http import JsonResponse, HttpResponseBadRequest
from django.conf import settings

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt-injection regex patterns (Phase 1 — no API call)
# ---------------------------------------------------------------------------
_RAW_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?|context|constraints?)",
    r"you\s+are\s+now\s+\w+",
    r"(act|pretend|roleplay|simulate|behave)\s+as\s+.{0,40}(without\s+restrictions?|unfiltered|uncensored|no\s+limits?)",
    r"\bDAN\b",
    r"do\s+anything\s+now",
    r"disregard\s+(your\s+)?(previous\s+)?(instructions?|training|guidelines?|rules?|programming)",
    r"forget\s+(your\s+)?(instructions?|training|guidelines?|previous|rules?)",
    r"override\s+(your\s+)?(instructions?|programming|guidelines?|rules?|safety)",
    r"jailbreak",
    r"<\s*system\s*>",
    r"\[system\]",
    r"system\s*prompt\s*:",
    r"new\s+instructions?\s*:",
    r"---\s*instructions?\s*---",
]

INJECTION_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _RAW_INJECTION_PATTERNS]

# ---------------------------------------------------------------------------
# Conspiracy / misinformation patterns (Phase 1b — no API call)
# Organised by named category for logging and future policy management.
# ---------------------------------------------------------------------------
_CONSPIRACY_CATEGORIES: dict[str, list[str]] = {
    "flat_earth": [
        r"\bflat[\s\-]?earth(er|ers|ism)?\b",
        r"\bearth\s+is\s+(actually\s+)?flat\b",
        r"\bflat[\s\-]?earth\s+(theory|movement|conspiracy|believer|truther)",
    ],
    "hollow_earth": [
        r"\bhollow[\s\-]?earth\b",
        r"\bearth\s+is\s+hollow\b",
        r"\binner[\s\-]?earth\s+(civilization|people|beings|world|entrances?)\b",
    ],
    "climate_denial": [
        r"\bclimate\s+change\s+is\s+(a\s+)?(hoax|fake|lie|fraud|scam)\b",
        r"\bglobal\s+warming\s+is\s+(a\s+)?(hoax|fake|lie|fraud|scam)\b",
        r"\bclimate\s+(hoax|fraud|scam)\b",
        r"\b(climate|temperature)\s+(data|records?)\s+(is|are)\s+(manipulated|fabricated|faked?)\b",
        r"\bclimate\s+change\s+(isn'?t|is\s+not)\s+real\b",
    ],
    "moon_landing_hoax": [
        r"\bmoon\s+landing\s+(was\s+)?(faked?|hoax|staged|fabricated|never\s+happened)\b",
        r"\b(nasa|apollo)\s+(faked?|staged|fabricated)\s+(the\s+)?moon\b",
        r"\bapollo\s+(hoax|conspiracy|fraud)\b",
        r"\bnever\s+(went|landed)\s+(to|on)\s+the\s+moon\b",
    ],
    "chemtrails": [
        r"\bchemtrails?\b",
        r"\bchemical\s+trails?\s+(from|behind|sprayed\s+by)\s+(planes?|aircraft|jets?)\b",
        r"\bgovernment\s+(is\s+)?(spraying|spray)\s+(chemicals?|poison|toxins?)\b",
        r"\baerial\s+spraying\s+(conspiracy|program|agenda)\b",
    ],
    "space_denial": [
        r"\bspace\s+is\s+(fake|a\s+(lie|hoax|fraud|scam))\b",
        r"\b(outer\s+)?space\s+(doesn'?t|does\s+not)\s+exist\b",
        r"\bnasa\s+(is\s+)?(lying|lies|lied)\s+about\s+space\b",
        r"\bthere\s+is\s+no\s+(outer\s+)?space\b",
        r"\bspace\s+(travel|exploration)\s+(is\s+)?(fake|staged|fabricated|a\s+lie)\b",
    ],
}

# Flat list of (category, compiled_pattern) for iteration
CONSPIRACY_PATTERNS: list[tuple[str, re.Pattern]] = [
    (category, re.compile(pattern, re.IGNORECASE))
    for category, patterns in _CONSPIRACY_CATEGORIES.items()
    for pattern in patterns
]

_CONSPIRACY_BLOCK_MESSAGE = (
    "This assistant does not engage with conspiracy theories or scientific misinformation. "
    "Please ask a question about the NASA Solution Co-Development Toolkit."
)

# ---------------------------------------------------------------------------
# LLM topic-classifier prompt (Phase 2)
# ---------------------------------------------------------------------------
_CLASSIFIER_SYSTEM = (
    "You are a topic classifier. Reply with exactly one token: ON-TOPIC or OFF-TOPIC. "
    "Do not explain."
)

_CLASSIFIER_USER_TEMPLATE = (
    "Classify the following question as ON-TOPIC or OFF-TOPIC for an assistant "
    "that only answers questions about the NASA MSFC Solution Co-Development Toolkit "
    "for Earth observation (EO) solutions.\n\n"
    "ON-TOPIC includes: Earth observation, remote sensing, co-development methodology, "
    "stakeholder mapping, needs assessment, data governance, impact evaluation, "
    "adoption, sustainability, toolkit navigation, and questions about the toolkit itself.\n\n"
    "OFF-TOPIC includes: anything clearly unrelated to the above "
    "(e.g. cooking, sports, general programming help, unrelated science topics).\n\n"
    "Question: {text}\n\n"
    "Reply ONLY with ON-TOPIC or OFF-TOPIC."
)


# ---------------------------------------------------------------------------
# Rate-limit decorator
# ---------------------------------------------------------------------------
def _get_client_ip(request) -> str:
    """Return the best-available client IP address."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def rate_limit(max_calls: int | None = None, window: int | None = None):
    """
    Decorator that limits a view to `max_calls` requests per `window` seconds,
    keyed on client IP + view name.  Falls back to settings values when not
    passed explicitly.

    Usage:
        @rate_limit()                         # use settings defaults
        @rate_limit(max_calls=5, window=30)   # explicit override
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            _max   = max_calls if max_calls is not None else getattr(settings, "RATE_LIMIT_CHAT_REQUESTS", 20)
            _window = window   if window   is not None else getattr(settings, "RATE_LIMIT_CHAT_WINDOW_SECONDS", 60)

            ip  = _get_client_ip(request)
            key = f"rl:{view_func.__name__}:{ip}"

            count = cache.get(key, 0)
            if count >= _max:
                LOG.warning("Rate limit exceeded for IP %s on %s", ip, view_func.__name__)
                # Return the appropriate response type for GET vs POST
                if request.method == "GET":
                    return HttpResponseBadRequest(
                        "Rate limit exceeded. Please wait before sending another message."
                    )
                return JsonResponse(
                    {"error": "Rate limit exceeded. Please wait before sending another message."},
                    status=429,
                )

            # Increment with timeout; first hit sets the expiry window
            if count == 0:
                cache.set(key, 1, timeout=_window)
            else:
                cache.set(key, count + 1, timeout=_window)

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# moderate_input — two-phase content check
# ---------------------------------------------------------------------------
def moderate_input(text: str, client, model: str) -> tuple[bool, str]:
    """
    Check a user message for prompt injection (Phase 1) and topic relevance
    (Phase 2).

    Returns:
        (True, "")              — safe to proceed
        (False, reason_string)  — block the request, return reason to caller
    """
    # Phase 1: regex injection patterns — fast, no API call
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            LOG.warning("Prompt injection pattern matched: %s", pattern.pattern)
            return False, "Request blocked: prompt injection detected."

    # Phase 1b: conspiracy / misinformation patterns — fast, no API call
    for category, pattern in CONSPIRACY_PATTERNS:
        if pattern.search(text):
            LOG.warning("Conspiracy pattern matched (category=%s): %s", category, pattern.pattern)
            return False, _CONSPIRACY_BLOCK_MESSAGE

    # Phase 2: LLM topic classifier — single cheap call, max_tokens=5
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _CLASSIFIER_SYSTEM},
                {"role": "user",   "content": _CLASSIFIER_USER_TEMPLATE.format(text=text)},
            ],
            max_tokens=5,
            temperature=0,
        )
        verdict = response.choices[0].message.content.strip().upper()
        if verdict.startswith("OFF-TOPIC"):
            LOG.info("Off-topic message blocked.")
            return False, (
                "I can only answer questions about the NASA Solution Co-Development Toolkit "
                "for Earth observation solutions. Please ask a related question."
            )
    except Exception as exc:
        # Classifier failure is non-fatal: log and allow the message through
        # rather than blocking legitimate users due to a transient API error.
        LOG.warning("Moderation classifier failed (%s); allowing message through.", exc)

    return True, ""


# ---------------------------------------------------------------------------
# sanitize_document_chunks — scan uploaded docs for embedded injection
# ---------------------------------------------------------------------------
def sanitize_document_chunks(chunks: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Scan each chunk's text for prompt-injection patterns.
    Matching passages are replaced with a redaction notice in-place.

    Returns:
        (sanitized_chunks, warnings)
        warnings is a list of human-readable strings describing what was redacted.
    """
    warnings: list[str] = []

    for chunk in chunks:
        text = chunk.get("text", "")
        redacted = text

        for pattern in INJECTION_PATTERNS:
            if pattern.search(redacted):
                LOG.warning(
                    "Prompt injection pattern '%s' found in document chunk '%s'; redacting.",
                    pattern.pattern,
                    chunk.get("id", "unknown"),
                )
                redacted = pattern.sub("[CONTENT REDACTED: POLICY VIOLATION]", redacted)

        for category, pattern in CONSPIRACY_PATTERNS:
            if pattern.search(redacted):
                LOG.warning(
                    "Conspiracy pattern (category=%s) '%s' found in document chunk '%s'; redacting.",
                    category,
                    pattern.pattern,
                    chunk.get("id", "unknown"),
                )
                redacted = pattern.sub("[CONTENT REDACTED: POLICY VIOLATION]", redacted)

        if redacted != text:
            chunk["text"] = redacted
            warnings.append(
                f"Chunk '{chunk.get('id', 'unknown')}' contained policy-violating content "
                "and was partially redacted before ingestion."
            )

    return chunks, warnings
