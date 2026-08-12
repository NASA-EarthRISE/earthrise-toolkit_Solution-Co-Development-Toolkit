"""
WSGI config for solution_co_development_toolkit project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "solution_co_development_toolkit.settings"
)

_django_app = get_wsgi_application()

# Read from settings.FORCE_SCRIPT_NAME — the authoritative source — so this
# works regardless of whether the value was loaded via python-dotenv (which
# writes to os.environ) or python-decouple (which does not).
_SCRIPT_NAME = getattr(settings, "FORCE_SCRIPT_NAME", None) or ""


def application(environ, start_response):
    if _SCRIPT_NAME:
        # Explicitly set SCRIPT_NAME in the WSGI environ.  nginx does not pass
        # this key even when a rewrite rule is active.
        environ["SCRIPT_NAME"] = _SCRIPT_NAME

        # If nginx has NOT rewritten the URL, PATH_INFO still contains the full
        # prefix — strip it so Django URL routing sees the relative path.
        # If nginx HAS rewritten it already, PATH_INFO is clean and this is a
        # no-op, making the nginx rewrite rule optional in either case.
        path = environ.get("PATH_INFO", "/")
        if path.startswith(_SCRIPT_NAME):
            environ["PATH_INFO"] = path[len(_SCRIPT_NAME):] or "/"

    return _django_app(environ, start_response)
