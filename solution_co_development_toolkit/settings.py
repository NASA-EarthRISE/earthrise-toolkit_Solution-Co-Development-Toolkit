import os

from dotenv import load_dotenv

load_dotenv()

from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY","dev-secret")
DEBUG = os.getenv("DJANGO_DEBUG","True")=="True"

ALLOWED_HOSTS = ['*']

# Sub-path deployment (e.g. https://host/earthrise-toolkit/solution-co-development-toolkit/)
# Set SCRIPT_NAME in .env for production; leave blank (or omit) for local dev.
SCRIPT_NAME = os.getenv("SCRIPT_NAME", "")
if SCRIPT_NAME:
    FORCE_SCRIPT_NAME = SCRIPT_NAME
    USE_X_FORWARDED_HOST = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# CSRF — always trust localhost for dev; extend via comma-separated env var for production.
# e.g. CSRF_TRUSTED_ORIGINS=https://science-dev.data.nasa.gov
CSRF_TRUSTED_ORIGINS = ['http://localhost', 'http://127.0.0.1']
_extra_csrf = os.getenv("CSRF_TRUSTED_ORIGINS", "")
if _extra_csrf:
    CSRF_TRUSTED_ORIGINS += [o.strip() for o in _extra_csrf.split(',') if o.strip()]

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    'webapp.apps.WebappConfig',
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "solution_co_development_toolkit.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / 'templates']
        ,
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "solution_co_development_toolkit.wsgi.application"


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = f"{SCRIPT_NAME}/static/" if SCRIPT_NAME else "static/"
STATICFILES_DIRS = [ BASE_DIR / "webapp" / "static" ]

STATIC_ROOT = BASE_DIR / 'staticfiles'

# Cache — used for rate limiting; FileBasedCache works across multiple workers
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": os.path.join(BASE_DIR, "django_cache"),
    }
}

# Chat safety settings
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "2000"))
RATE_LIMIT_CHAT_REQUESTS = int(os.getenv("RATE_LIMIT_CHAT_REQUESTS", "20"))
RATE_LIMIT_CHAT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_CHAT_WINDOW_SECONDS", "60"))

# App settings
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
MODEL           = os.getenv("MODEL","gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL","text-embedding-3-large")
RAG_MODE        = os.getenv("RAG_MODE","shared")

RAG_EMBEDDINGS_PROVIDER = os.getenv("RAG_EMBEDDINGS_PROVIDER","openai").lower()
LOCAL_EMBEDDING_MODEL   = os.getenv("LOCAL_EMBEDDING_MODEL","sentence-transformers/all-MiniLM-L6-v2")

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "chroma_db")
CHROMA_COLLECTION  = os.getenv("CHROMA_COLLECTION", "pi_assist_docs")

LITELLM_RAG_SEARCH = os.getenv("LITELLM_RAG_SEARCH","/rag/search")
LITELLM_RAG_UPSERT = os.getenv("LITELLM_RAG_UPSERT","/rag/upsert")

# Shared Embedding Service
SHARED_EMBEDDING_SERVICE_URL     = os.getenv("SHARED_EMBEDDING_SERVICE_URL", "http://localhost:8000")
SHARED_EMBEDDING_SERVICE_API_KEY = os.getenv("SHARED_EMBEDDING_SERVICE_API_KEY", "")

# ── AI Assistant visibility ──────────────────────────────────────────────────
# Set to True  → chat widget visible to staff only (temporary restriction).
# Set to False → chat widget visible to all visitors (normal public access).
CHAT_STAFF_ONLY = os.getenv("CHAT_STAFF_ONLY", "True").lower() == "true"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "webapp": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
