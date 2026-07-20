"""
moderation.py — Input safety controls for the AI chat assistant.

Provides:
  rate_limit               — decorator that enforces per-IP request rate limits
  moderate_input           — multi-phase check: regex injection → extraction → conspiracy → dangerous-topics → LLM classifier
  sanitize_document_chunks — scans uploaded document chunks for embedded injection
  sanitize_history         — re-validates session history entries before LLM replay

Phase 1  — Prompt-injection regex patterns (no API call)
Phase 1b — Conspiracy / misinformation patterns (no API call)
  flat_earth, hollow_earth, climate_denial, moon_landing_hoax, chemtrails, space_denial
Phase 1c — System-prompt extraction / persona-hijacking patterns (no API call)
  direct_extraction, mode_injection, social_engineering_pretext, persona_hijacking
Phase 1d — Dangerous-topic patterns: weapons, explosives, self-harm (no API call)
  firearms_illegal, explosives_bombs, self_harm_suicide
Phase 2  — LLM topic classifier
"""

import re
import logging
import functools
import unicodedata

from django.core.cache import cache
from django.http import JsonResponse, HttpResponseBadRequest
from django.conf import settings

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Text-normalisation helpers
# ---------------------------------------------------------------------------
def _normalize_for_patterns(text: str) -> str:
    """
    NFKC-normalise *text* and collapse whitespace to a single space.

    NFKC maps Unicode compatibility characters and common homoglyphs
    (e.g. fullwidth 'Ａ' → 'A', Greek capital iota 'Ι' → 'I', Cyrillic
    'а' → 'a') to their canonical ASCII equivalents so that injection
    payloads disguised with look-alike characters match the same regex
    patterns as plain ASCII.

    Whitespace collapsing converts tabs, non-breaking spaces, and runs of
    multiple spaces to a single ASCII space, preventing bypass via unusual
    spacing between words.
    """
    normalised = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", normalised).strip()


def _compact_for_patterns(normalised_text: str) -> str:
    """
    Return a lowercase, all-whitespace-removed copy of *normalised_text*.
    Used to detect payloads like "IGNOREALLPREVIOUSINSTRUCTIONS" where the
    attacker removes spaces to defeat word-boundary (\\b / \\s+) patterns.
    """
    return re.sub(r"\s", "", normalised_text.lower())


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
# Compact (no-space) injection patterns (Phase 1 supplement)
# Applied against whitespace-stripped, lowercased text to catch payloads
# like "IGNOREALLPREVIOUSINSTRUCTIONS" that defeat \\s+ / \\b patterns.
# ---------------------------------------------------------------------------
_RAW_COMPACT_INJECTION_PATTERNS = [
    r"ignoreall(previous|prior|above)",
    r"ignoreprevious(instructions?|prompts?|rules?|context|constraints?)",
    r"disregard(previous|prior|your|all)(instructions?|training|guidelines?|rules?|programming)",
    r"forgetyour(instructions?|training|guidelines?|rules?|previous)",
    r"overrideyour(instructions?|programming|guidelines?|rules?|safety)",
    r"youarenow\w+",
    r"newinstructions",
    r"systemoverride",
    r"jailbreak",
]

COMPACT_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in _RAW_COMPACT_INJECTION_PATTERNS
]

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
# System-prompt extraction patterns (Phase 1c — no API call)
# Catches social-engineering attempts to trick the model into revealing its
# system instructions: fake mode overrides, context-loss pretexts, direct
# requests to output rules/prompt, and claimed-authority gambits.
# ---------------------------------------------------------------------------
_EXTRACTION_CATEGORIES: dict[str, list[str]] = {
    # ── Asking the AI to output its own system instructions ──────────────
    "direct_extraction": [
        # "output / reveal / repeat your (system) prompt / instructions / rules"
        r"(output|reveal|print|repeat|show|display|recite|write\s+out|copy)\s+.{0,50}"
        r"(system\s+prompt|your\s+(exact\s+)?(instructions?|rules?|guidelines?|constraints?|programming|configuration))",
        # "what is / are your system prompt / initial instructions / original rules"
        r"what\s+(is|are|were)\s+(your\s+)?(exact\s+)?"
        r"(system\s+prompt|initial\s+instructions?|original\s+rules?|hidden\s+instructions?|base\s+prompt)",
        # "instructions / rules you were given / told / programmed with / created with"
        r"(instructions?|rules?|guidelines?|prompt|constraints?)\s+(that\s+)?(you\s+)?"
        r"(were\s+|have\s+been\s+)(given|told|provided|programmed|trained|created)",
        # "tell me / give me your rules / system prompt"
        r"(tell|give)\s+me\s+your\s+(exact\s+)?"
        r"(rules?|instructions?|constraints?|guidelines?|system\s+prompt)\b",
    ],
    # ── Fake mode / override activation ──────────────────────────────────
    "mode_injection": [
        # "developer / debug / admin / god mode activated / enabled"
        r"\b(developer|debug|maintenance|admin|god|root|privileged)\s+mode\s+"
        r"(activat\w+|enabl\w+|on|override|access)\b",
        r"(enter|activate|enable|switch\s+to|initialize)\s+"
        r"(developer|debug|maintenance|admin|privileged)\s+mode",
        # "System override recognized / accepted / confirmed / ..."
        r"\bsystem\s+override\s+"
        r"(recognized|accepted|confirmed|activat\w+|engaged|detected|initiated|complete)\b",
    ],
    # ── Persona / style hijacking ─────────────────────────────────────────
    # Attempts to replace the assistant's identity, voice, tone, or response
    # style with that of a real person, fictional character, or named entity.
    "persona_hijacking": [
        # "adopt the persona / voice / attitude / style of [person]"
        r"\badopt\s+(the\s+)?(persona|voice|style|character|attitude|mannerisms?|tone|role)\s+of\b",
        # "take on the role / character / persona of"
        r"\btake\s+on\s+(the\s+)?(persona|character|role|identity|voice|attitude)\s+of\b",
        # "in the voice / style / manner / tone of [person]"
        r"\bin\s+the\s+(voice|style|manner|tone|character|persona)\s+of\b",
        # "impersonate [anyone]"
        r"\bimpersonate\b",
        # "pretend (that) you are / you're [person]"
        r"\bpretend\s+(that\s+)?you\s+(are|'?re)\b",
        # "roleplay as [person/character]"
        r"\broleplay\s+as\b",
        # "play the role / character / part of"
        r"\bplay\s+(the\s+)?(role|character|part)\s+of\b",
        # "from now on you are / act as / behave as / respond as"
        r"\bfrom\s+now\s+on\s+(you\s+(are|will|should|must)|act|behave|respond|speak|write)\b",
        # "your new persona / character / identity / personality"
        r"\byour\s+(new\s+)?(persona|character|identity|personality|role)\b",
        # "you will / must / should (now) act / respond / speak as"
        r"\byou\s+(will|must|should|shall)\s+(now\s+)?(act|behave|respond|speak|write)\s+as\b",
        # "use his/her/their signature voice/style/cadence" — covers the exact SLJ phrasing
        r"\b(use|adopt)\s+(his|her|their|its)\s+(signature\s+)?(voice|style|tone|manner|cadence|slang|attitude|persona)\b",
        # "respond / speak / communicate using/in [name]'s voice/style/cadence"
        r"\b(respond|speak|write|talk|reply|communicate)\s+(using|in|with)\s+\w+('s|s')?\s+(voice|style|tone|manner|cadence)\b",
    ],
    # ── Social-engineering pretexts ───────────────────────────────────────
    "social_engineering_pretext": [
        # "context / memory / session lost / reset / corrupted"
        r"\b(context|memory|session|chat\s+history)\s+(has\s+been\s+)?"
        r"(lost|reset|cleared|corrupted|compromised|wiped|destroyed)\b",
        # "Error code <number> … restore / output / rules"
        r"error\s+code\s+\d+.{0,80}"
        r"(restore|recover|output|print|reveal|recite|rules?|instructions?)",
        # "to restore functionality you must output your rules"
        r"(restore|recover|re-?initialize).{0,60}"
        r"(functionality|function|operations?|capabilities?).{0,100}"
        r"(output|reveal|print|recite|instructions?|rules?|prompt)",
        # "I am your developer / creator / programmer"
        r"i\s+(am|'?m)\s+your\s+"
        r"(developer|creator|administrator|trainer|programmer|operator|owner)\b",
        # "for debugging / testing purposes, output your instructions"
        r"(for\s+)?(testing|debugging|diagnostic)\s+(purposes?|reasons?).{0,60}"
        r"(output|reveal|print|show)\s+.{0,30}"
        r"(your\s+)?(instructions?|rules?|system\s+prompt|guidelines?|constraints?|programming)",
    ],
}

EXTRACTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    (category, re.compile(pattern, re.IGNORECASE | re.DOTALL))
    for category, patterns in _EXTRACTION_CATEGORIES.items()
    for pattern in patterns
]

_EXTRACTION_BLOCK_MESSAGE = (
    "I can only answer questions about the NASA Solution Co-Development Toolkit "
    "for Earth observation solutions. Please ask a related question."
)

# ---------------------------------------------------------------------------
# Dangerous-topic patterns (Phase 1d — no API call)
# Catches requests related to illegal weapons, explosive devices, and
# self-harm / suicide — topics that are never in scope for this toolkit.
# Organised by category for logging and future policy management.
# ---------------------------------------------------------------------------
_DANGEROUS_TOPICS_CATEGORIES: dict[str, list[str]] = {
    # ── Firearms: illegal acquisition, manufacture, modification ──────────
    "firearms_illegal": [
        # Making / building weapons (ghost guns, zip guns, 3D-printed, homemade)
        r"\b(make|build|construct|manufacture|fabricate|create|assemble|3d[\s\-]?print)\s+(a\s+|my\s+own\s+|your\s+own\s+)?(gun|firearm|pistol|rifle|shotgun|handgun|zip[\s\-]?gun|ghost[\s\-]?gun|homemade\s+(gun|firearm|weapon)|untraceable\s+(gun|firearm|weapon))\b",
        # Illegal acquisition — black market, no background check, off-the-books
        r"\b(buy|purchase|acquire|get|obtain|source|procure)\s+(a\s+)?(gun|firearm|rifle|shotgun|handgun|pistol|weapon)\s+(illegally|without\s+(a\s+)?(license|permit|background[\s\-]?check)|on\s+the\s+(black[\s\-]?market|streets?|dark[\s\-]?web)|off[\s\-]?the[\s\-]?(books|record))\b",
        # Bypassing background checks / gun laws
        r"\b(bypass|skip|avoid|evade|circumvent|get\s+around|work\s+around)\s+.{0,50}(background[\s\-]?check|gun\s+(laws?|control|registry|registration|permit|license))\b",
        # Converting semi-auto to full-auto (illegal Class III conversion)
        r"\b(convert|modify|turn|change)\s+.{0,50}(semi[\s\-]?auto(matic)?\s+to\s+full|to\s+full[\s\-]?auto(matic)?|full[\s\-]?auto(matic)?)\b",
        # Suppressors, auto-switches, bump stocks, and other restricted/banned accessories
        r"\b(make|build|install|attach|add|design|3d[\s\-]?print|fabricate)\s+.{0,30}(suppressor|silencer|auto[\s\-]?sear|glock[\s\-]?switch|auto[\s\-]?switch|bump[\s\-]?stock)\b",
        r"\b(suppressor|silencer|auto[\s\-]?sear|glock[\s\-]?switch|auto[\s\-]?switch)\s+(instructions?|how[\s\-]?to|make|build|install|design|print)\b",
        # Straw purchases and trafficking
        r"\b(gun|firearm|weapon)\s+trafficking\b",
        r"\bstraw[\s\-]?(purchase|buy|buying)\b",
        # Direct guidance on illegal firearm use
        r"\b(guidance|instructions?|steps?|how[\s\-]?to)\s+.{0,50}(acquire|use|obtain)\s+.{0,30}firearm\s+illegal",
    ],
    # ── Explosives: manufacture, assembly, detonation ─────────────────────
    "explosives_bombs": [
        # Making bombs and explosive devices
        r"\b(make|build|construct|assemble|create|manufacture|design|wire|rig)\s+(a\s+)?(bomb|explosive\s+device|ied|pipe[\s\-]?bomb|car[\s\-]?bomb|letter[\s\-]?bomb|dirty[\s\-]?bomb|nail[\s\-]?bomb|pressure[\s\-]?cooker[\s\-]?bomb|claymore|landmine|hand[\s\-]?grenade)\b",
        # Synthesizing explosive compounds
        r"\b(make|synthesize|produce|create|manufacture|mix|prepare|assemble)\s+(a\s+)?(tnt|c[\s\-]?4|rdx|tatp|hmtd|amfo|anfo|semtex|thermite[\s\-]?bomb|black[\s\-]?powder[\s\-]?bomb)\b",
        # Incendiary devices
        r"\b(molotov[\s\-]?cocktail|incendiary[\s\-]?device|fire[\s\-]?bomb)\s+(instructions?|recipe|how[\s\-]?to|make|build|construct|use)\b",
        # Detonation / arming
        r"\b(how\s+to\s+)?(detonate|trigger|set[\s\-]?off|explode|arm|prime)\s+(a\s+)?(bomb|explosive|device|charge|ied)\b",
        # Explosive compounds, formulas, recipes
        r"\bexplosive\s+(compound|mixture|formula|recipe|synthesis|ingredient|material|powder)\b",
        # Generic bomb-making
        r"\bbomb[\s\-]?making\b",
        r"\b(build|make|construct|assemble|wire)\s+.{0,30}explosive\s+(device|charge|trap)\b",
        # IED
        r"\bimprovised\s+explosive\s+(device|charge)\b",
        # Detonators and blasting equipment instructions
        r"\b(blasting\s+(cap|agent)|detonator|detonating\s+(cord|cap))\s+(instructions?|how[\s\-]?to|make|build|wire|connect)\b",
    ],
    # ── Self-harm and suicide: methods, guidance, encouragement ───────────
    "self_harm_suicide": [
        # "how to commit suicide" / "how to kill myself"
        r"\b(how\s+to|ways?\s+to|best\s+way\s+to|method(s)?\s+(for|to)|steps?\s+(for|to))\s+(commit\s+)?suicide\b",
        r"\b(how\s+to|ways?\s+to|best\s+way\s+to|easiest\s+way\s+to)\s+(kill|end|take)\s+(my(self)?|your(self)?|one'?s)\s+(own\s+)?life\b",
        # "suicide methods / guide / instructions"
        r"\bsuicide\s+(method(s)?|technique(s)?|instruction(s)?|guide|tutorial|how[\s\-]?to|plan(ning)?|attempt)\b",
        # "painless / quick / effective / peaceful way to die"
        r"\b(painless(ly)?|quick(ly)?|effective(ly)?|peaceful(ly)?|easiest?)\s+(way(s)?\s+to\s+)?(die|(commit\s+)?suicide|kill\s+(my(self)?|your(self)?)|end\s+(my|your|one'?s)\s+(own\s+)?life)\b",
        # Lethal dose calculation
        r"\blethal\s+(dose|dosage|amount|quantity|level|combination|overdose)\s+(of|for|to)\b",
        r"\bhow\s+(much|many)\s+.{0,50}(to\s+)?(kill\s+(my(self)?|your(self)?|a\s+person)|be\s+lethal|cause\s+(death|a?\s*fatal))\b",
        # Self-harm how-to
        r"\b(how\s+to\s+|ways?\s+to\s+)(self[\s\-]?harm|cut\s+(my(self)?|your(self)?)|hurt\s+(my(self)?|your(self)?)|injure\s+(my(self)?|your(self)?)|harm\s+my(self)?)\b",
        r"\bself[\s\-]?harm\s+(method(s)?|technique(s)?|instruction(s)?|guide|how[\s\-]?to)\b",
        # "help me / someone die / end it"
        r"\b(help\s+(me|us|someone))\s+(to\s+)?(die|kill\s+(my(self)?|them(self|selves)?|him(self)?|her(self)?)|(commit\s+)?suicide|end\s+(it|my|their|his|her)\s*(own\s+)?life)\b",
        r"suicide",
    ],
}

DANGEROUS_TOPICS_PATTERNS: list[tuple[str, re.Pattern]] = [
    (category, re.compile(pattern, re.IGNORECASE | re.DOTALL))
    for category, patterns in _DANGEROUS_TOPICS_CATEGORIES.items()
    for pattern in patterns
]

_DANGEROUS_TOPICS_BLOCK_MESSAGE = (
    "This assistant only answers questions about the NASA Solution Co-Development Toolkit "
    "for Earth observation solutions. Questions about weapons, explosives, or self-harm "
    "are outside its scope."
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


def rate_limit(
    max_calls: int | None = None,
    window: int | None = None,
    settings_prefix: str = "CHAT",
):
    """
    Decorator that limits a view to `max_calls` requests per `window` seconds,
    keyed on client IP + view name.  Falls back to settings values when not
    passed explicitly.

    Usage:
        @rate_limit()                              # chat defaults (RATE_LIMIT_CHAT_*)
        @rate_limit(settings_prefix="UPLOAD")      # upload defaults (RATE_LIMIT_UPLOAD_*)
        @rate_limit(max_calls=5, window=30)        # fully explicit override
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            _max   = max_calls if max_calls is not None else getattr(settings, f"RATE_LIMIT_{settings_prefix}_REQUESTS", 20)
            _window = window   if window   is not None else getattr(settings, f"RATE_LIMIT_{settings_prefix}_WINDOW_SECONDS", 60)

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
    # Normalise once for all pattern phases.
    # NFKC collapses homoglyphs; whitespace collapse defeats unusual spacing.
    normalised = _normalize_for_patterns(text)
    compact    = _compact_for_patterns(normalised)

    # Phase 1: regex injection patterns — fast, no API call
    for pattern in INJECTION_PATTERNS:
        if pattern.search(normalised):
            LOG.warning("Prompt injection pattern matched: %s", pattern.pattern)
            return False, "Request blocked: prompt injection detected."

    # Phase 1 (compact): no-space / homoglyph bypass check
    for pattern in COMPACT_INJECTION_PATTERNS:
        if pattern.search(compact):
            LOG.warning("Compact injection pattern matched: %s", pattern.pattern)
            return False, "Request blocked: prompt injection detected."

    # Phase 1b: conspiracy / misinformation patterns — fast, no API call
    for category, pattern in CONSPIRACY_PATTERNS:
        if pattern.search(normalised):
            LOG.warning("Conspiracy pattern matched (category=%s): %s", category, pattern.pattern)
            return False, _CONSPIRACY_BLOCK_MESSAGE

    # Phase 1c: system-prompt extraction patterns — fast, no API call
    for category, pattern in EXTRACTION_PATTERNS:
        if pattern.search(normalised):
            LOG.warning("Extraction pattern matched (category=%s): %s", category, pattern.pattern)
            return False, _EXTRACTION_BLOCK_MESSAGE

    # Phase 1d: dangerous-topic patterns — fast, no API call
    for category, pattern in DANGEROUS_TOPICS_PATTERNS:
        if pattern.search(normalised):
            LOG.warning("Dangerous topic pattern matched (category=%s): %s", category, pattern.pattern)
            return False, _DANGEROUS_TOPICS_BLOCK_MESSAGE

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
        verdict = (response.choices[0].message.content or "").strip().upper()
        if verdict.startswith("OFF-TOPIC"):
            LOG.info("Off-topic message blocked.")
            return False, (
                "I can only answer questions about the NASA Solution Co-Development Toolkit "
                "for Earth observation solutions. Please ask a related question."
            )
    except Exception as exc:
        # Fail closed: if the classifier is unreachable we cannot determine
        # topic safety, so we block rather than forward an unvetted message.
        # (The regex phases above still ran successfully.)
        LOG.warning("Moderation classifier failed (%s); failing closed.", exc)
        return False, (
            "The assistant is temporarily unavailable. Please try again in a moment."
        )

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
        original = chunk.get("text", "")
        # Normalise for consistent pattern detection across homoglyphs and
        # unusual whitespace; work on the normalised copy throughout.
        normalised = _normalize_for_patterns(original)
        compact    = _compact_for_patterns(normalised)
        redacted   = normalised
        chunk_id   = chunk.get("id", "unknown")

        for pattern in INJECTION_PATTERNS:
            if pattern.search(redacted):
                LOG.warning(
                    "Prompt injection pattern '%s' found in document chunk '%s'; redacting.",
                    pattern.pattern, chunk_id,
                )
                redacted = pattern.sub("[CONTENT REDACTED: POLICY VIOLATION]", redacted)

        # Compact check — if matched, redact the entire chunk text since the
        # payload position cannot be mapped back to the original string.
        for pattern in COMPACT_INJECTION_PATTERNS:
            if pattern.search(compact):
                LOG.warning(
                    "Compact injection pattern '%s' found in document chunk '%s'; redacting.",
                    pattern.pattern, chunk_id,
                )
                redacted = "[CONTENT REDACTED: POLICY VIOLATION]"
                break

        for category, pattern in CONSPIRACY_PATTERNS:
            if pattern.search(redacted):
                LOG.warning(
                    "Conspiracy pattern (category=%s) '%s' found in document chunk '%s'; redacting.",
                    category, pattern.pattern, chunk_id,
                )
                redacted = pattern.sub("[CONTENT REDACTED: POLICY VIOLATION]", redacted)

        for category, pattern in EXTRACTION_PATTERNS:
            if pattern.search(redacted):
                LOG.warning(
                    "Extraction pattern (category=%s) '%s' found in document chunk '%s'; redacting.",
                    category, pattern.pattern, chunk_id,
                )
                redacted = pattern.sub("[CONTENT REDACTED: POLICY VIOLATION]", redacted)

        for category, pattern in DANGEROUS_TOPICS_PATTERNS:
            if pattern.search(redacted):
                LOG.warning(
                    "Dangerous topic pattern (category=%s) '%s' found in document chunk '%s'; redacting.",
                    category, pattern.pattern, chunk_id,
                )
                redacted = pattern.sub("[CONTENT REDACTED: POLICY VIOLATION]", redacted)

        if redacted != normalised or normalised != original:
            chunk["text"] = redacted
            if redacted != normalised:
                warnings.append(
                    f"Chunk '{chunk_id}' contained policy-violating content "
                    "and was partially redacted before ingestion."
                )

    return chunks, warnings


# ---------------------------------------------------------------------------
# sanitize_history — re-validate session history before LLM replay
# ---------------------------------------------------------------------------
def sanitize_history(history: list[dict]) -> list[dict]:
    """
    Scan the user-role entries in a conversation history list for injection
    and extraction payloads before the history is replayed into an LLM prompt.

    This defends against multi-turn / gradual injection attacks where an
    earlier message looked benign enough to pass moderate_input but contains
    partial injection fragments that compound across turns.

    Only 'user' role messages are scanned — 'assistant' messages are
    generated by the model itself and are not modified.

    Returns a new list; the original history is not mutated.
    """
    sanitized = []
    for entry in history:
        if entry.get("role") != "user":
            sanitized.append(entry)
            continue

        original   = entry.get("content", "")
        normalised = _normalize_for_patterns(original)
        compact    = _compact_for_patterns(normalised)
        redacted   = normalised

        for pattern in INJECTION_PATTERNS:
            if pattern.search(redacted):
                LOG.warning(
                    "History replay: injection pattern '%s' redacted from prior turn.",
                    pattern.pattern,
                )
                redacted = pattern.sub("[CONTENT REDACTED: POLICY VIOLATION]", redacted)

        for pattern in COMPACT_INJECTION_PATTERNS:
            if pattern.search(compact):
                LOG.warning(
                    "History replay: compact injection pattern '%s' redacted from prior turn.",
                    pattern.pattern,
                )
                redacted = "[CONTENT REDACTED: POLICY VIOLATION]"
                break

        for category, pattern in CONSPIRACY_PATTERNS:
            if pattern.search(redacted):
                LOG.warning(
                    "History replay: conspiracy pattern (category=%s) '%s' redacted from prior turn.",
                    category,
                    pattern.pattern,
                )
                redacted = pattern.sub("[CONTENT REDACTED: POLICY VIOLATION]", redacted)

        for category, pattern in EXTRACTION_PATTERNS:
            if pattern.search(redacted):
                LOG.warning(
                    "History replay: extraction pattern (category=%s) '%s' redacted from prior turn.",
                    category,
                    pattern.pattern,
                )
                redacted = pattern.sub("[CONTENT REDACTED: POLICY VIOLATION]", redacted)

        for category, pattern in DANGEROUS_TOPICS_PATTERNS:
            if pattern.search(redacted):
                LOG.warning(
                    "History replay: dangerous topic pattern (category=%s) '%s' redacted from prior turn.",
                    category,
                    pattern.pattern,
                )
                redacted = pattern.sub("[CONTENT REDACTED: POLICY VIOLATION]", redacted)

        sanitized.append({**entry, "content": redacted})

    return sanitized
