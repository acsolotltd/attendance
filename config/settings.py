"""Settings. Safe by default: nothing insecure runs unless DJANGO_DEBUG=1. See .env.example."""
import ipaddress
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """Tiny .env loader (real environment variables win)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def env_list(name, default=""):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "Set DJANGO_SECRET_KEY (python -c \"import secrets; print(secrets.token_urlsafe(50))\"), "
            "or DJANGO_DEBUG=1 for local development. See .env.example.")
    SECRET_KEY = "dev-only-insecure-key"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "*" if DEBUG else "")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "Set DJANGO_ALLOWED_HOSTS to your domain(s) AND the server's public IP: ADMS devices call the server "
        "by IP, so that IP arrives as the Host header (e.g. DJANGO_ALLOWED_HOSTS=hr.example.com,203.0.113.10).")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# --- HTTPS / proxy ----------------------------------------------------------------------------
BEHIND_PROXY = env_bool("DJANGO_BEHIND_PROXY", False)      # nginx/Caddy/Cloudflare in front
TRUST_PROXY_HEADERS = BEHIND_PROXY                          # only then is X-Forwarded-For believed
if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
HTTPS = env_bool("DJANGO_HTTPS", False)                     # UI is served over HTTPS
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = HTTPS
SECURE_SSL_REDIRECT = HTTPS and env_bool("DJANGO_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", 0) if HTTPS else 0
# Devices usually speak plain HTTP and cannot follow redirects: never redirect their endpoints.
SECURE_REDIRECT_EXEMPT = [r"^iclock/", r"^healthz$"]
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_COOKIE_SAMESITE = CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "attendance",
]

try:
    import whitenoise  # noqa: F401
    _WHITENOISE = True
except ImportError:  # dev without the package: runserver serves static files itself
    _WHITENOISE = False

MIDDLEWARE = (
    ["django.middleware.security.SecurityMiddleware"]
    + (["whitenoise.middleware.WhiteNoiseMiddleware"] if _WHITENOISE else [])
    + [
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "attendance.middleware.LoginRequiredMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
    ]
)

ROOT_URLCONF = "config.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "attendance.context.assets",
    ]},
}]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database: SQLite (WAL) is fine for tens of devices; PostgreSQL for more ----------------------------
if os.environ.get("DB_ENGINE", "sqlite") == "postgres":
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "attendance"), "USER": os.environ.get("DB_USER", "attendance"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""), "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"), "CONN_MAX_AGE": 60,
    }}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3")),
        "OPTIONS": {"timeout": 20},
    }}

# Shared by all gunicorn workers when DJANGO_CACHE_DIR is set (rate limits, login throttle).
if os.environ.get("DJANGO_CACHE_DIR"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                          "LOCATION": os.environ["DJANGO_CACHE_DIR"]}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
# Set this to the time zone your devices are set to: it decides what "now" means for Absent detection.
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "UTC")
USE_I18N = False
USE_TZ = False  # device timestamps are naive local wall-clock times; keep them untouched

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage" if _WHITENOISE
                    else "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = DEBUG
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # large ATTLOG batches

LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {"attendance": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")}},
}

# --- ADMS (push) receiver ---------------------------------------------------------------------------
# Unknown serial numbers are refused (403) and listed in the UI with a one-click Register button.
# Set to 1 only for quick tests: anyone who can reach the URL could then create devices.
ADMS_AUTO_REGISTER = env_bool("ADMS_AUTO_REGISTER", False)
ADMS_DELAY = env_int("ADMS_DELAY", 30)                        # seconds between device polls
ADMS_TRANS_FLAG = os.environ.get("ADMS_TRANS_FLAG", "")       # overrides every device's upload profile
ADMS_RATE_LIMIT_PER_MIN = env_int("ADMS_RATE_LIMIT_PER_MIN", 600)  # per source IP; 0 = off
ADMS_LOG_HEARTBEATS = env_bool("ADMS_LOG_HEARTBEATS", False)  # journal the routine "OK" polls too
ADMS_ALLOWED_NETWORKS = [ipaddress.ip_network(n, strict=False) for n in env_list("ADMS_ALLOWED_NETWORKS")]
