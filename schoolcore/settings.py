"""
Django settings for schoolcore project — an online school platform for Ghana
and the wider African market. Payments are handled by Paystack (GHS).
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader so we avoid extra dependencies."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


import os  # noqa: E402

_load_dotenv(BASE_DIR / ".env")

# Quick-start development settings - unsuitable for production
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-dev-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = ["127.0.0.1", "localhost", "0.0.0.0", "testserver"]
CSRF_TRUSTED_ORIGINS = ["http://localhost:8000", "http://127.0.0.1:8000"]

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.sitemaps",
    # Local apps
    "accounts",
    "courses",
    "community",
    "payments",
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

ROOT_URLCONF = "schoolcore.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.platform_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "schoolcore.wsgi.application"

# Database — SQLite for development. Switch to PostgreSQL for production.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_USER_MODEL = "accounts.User"

# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization — Ghana English, Africa/Accra time

LANGUAGE_CODE = "en-gh"
TIME_ZONE = "Africa/Accra"
USE_I18N = True
USE_TZ = True

# Static / media files

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Authentication

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:my_learning"
LOGOUT_REDIRECT_URL = "home"

# Email — prints to the console in development; set EMAIL_BACKEND=<SMTP backend>,
# EMAIL_HOST/USER/PASSWORD/PORT etc. in .env for production.
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "LearnSasa <hello@learnsasa.com>")
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")

# ---------------------------------------------------------------------------
# Platform business config
# ---------------------------------------------------------------------------

CURRENCY = os.environ.get("PLATFORM_CURRENCY", "GHS")
CURRENCY_SYMBOL = {"GHS": "GH₵", "NGN": "₦", "USD": "$"}.get(CURRENCY, CURRENCY)

# Platform takes this % of every paid course sale; the rest goes to the creator.
PLATFORM_COMMISSION_PERCENT = int(os.environ.get("PLATFORM_COMMISSION_PERCENT", "10"))

# Smallest amount a creator can request for payout (in major currency units).
PLATFORM_MIN_PAYOUT = int(os.environ.get("PLATFORM_MIN_PAYOUT", "50"))

# Paystack integration. Amounts passed to Paystack must be in minor units
# (pesewas for GHS, kobo for NGN).
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_API_BASE = "https://api.paystack.co"
