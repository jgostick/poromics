"""
Django settings for Poromics project.

For more information on this file, see
https://docs.djangoproject.com/en/stable/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/stable/ref/settings/
"""

import os
import sys
from pathlib import Path
from typing import Any

import environ
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy

from apps.pore_analysis.queue_catalog import (
    QueueCatalogError,
    build_backend_queue_map,
    build_queue_endpoint_map,
    default_catalog_path,
    load_queue_catalog,
)

# Build paths inside the project like this: BASE_DIR / "subdir".
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
env.read_env(os.path.join(BASE_DIR, ".env"))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/stable/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("SECRET_KEY", default="django-insecure-yE0lHtEuW0BSqKvzbkkKxPZkzwPGLWBjUFAfI5zD")

# SECURITY WARNING: don"t run with debug turned on in production!
DEBUG = env.bool("DEBUG", default=True)
ENABLE_DEBUG_TOOLBAR = env.bool("ENABLE_DEBUG_TOOLBAR", default=False) and "test" not in sys.argv

# Note: It is not recommended to set ALLOWED_HOSTS to "*" in production
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])


# Application definition

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sitemaps",
    "django.contrib.messages",
    "django.contrib.postgres",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.forms",
]

# Put your third-party apps here
THIRD_PARTY_APPS = [
    "allauth",  # allauth account/registration management
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.github",
    "channels",
    "django_htmx",
    "django_vite",
    "allauth.mfa",
    "rest_framework",
    "drf_spectacular",
    "rest_framework_api_key",
    "celery_progress",
    "hijack",  # "login as" functionality
    "hijack.contrib.admin",  # hijack buttons in the admin
    "whitenoise.runserver_nostatic",  # whitenoise runserver
    "waffle",
    "health_check",
    "django_celery_beat",
]

PEGASUS_APPS = [
    "pegasus.apps.examples.apps.PegasusExamplesConfig",
    "pegasus.apps.employees.apps.PegasusEmployeesConfig",
]

# Put your project-specific apps here
PROJECT_APPS = [
    "apps.users.apps.UserConfig",
    "apps.dashboard.apps.DashboardConfig",
    "apps.api.apps.APIConfig",
    "apps.web",
    "apps.teams.apps.TeamConfig",
    "apps.pore_analysis.apps.PoreAnalysisConfig",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + PEGASUS_APPS + PROJECT_APPS

if DEBUG:
    # in debug mode, add daphne to the beginning of INSTALLED_APPS to enable async support
    INSTALLED_APPS.insert(0, "daphne")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.teams.middleware.TeamsMiddleware",
    "apps.web.middleware.locale.UserLocaleMiddleware",
    "apps.web.middleware.locale.UserTimezoneMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "hijack.middleware.HijackUserMiddleware",
    "waffle.middleware.WaffleMiddleware",
]

if ENABLE_DEBUG_TOOLBAR:
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")
    INSTALLED_APPS.append("debug_toolbar")
    INTERNAL_IPS = ["127.0.0.1"]

# add browser reload only in debug mode
if DEBUG:
    INSTALLED_APPS.append("django_browser_reload")
    MIDDLEWARE.append("django_browser_reload.middleware.BrowserReloadMiddleware")

# add watchfiles only in debug mode
if DEBUG:
    INSTALLED_APPS.append("django_watchfiles")

ROOT_URLCONF = "poromics.urls"

# used to disable the cache in dev, but turn it on in production.
# more here: https://nickjanetakis.com/blog/django-4-1-html-templates-are-cached-by-default-with-debug-true
_DEFAULT_LOADERS = [
    "django.template.loaders.filesystem.Loader",
    "django.template.loaders.app_directories.Loader",
]

_CACHED_LOADERS = [("django.template.loaders.cached.Loader", _DEFAULT_LOADERS)]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates",
        ],
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.web.context_processors.project_meta",
                "apps.teams.context_processors.team",
                "apps.teams.context_processors.user_teams",
                # this line can be removed if not using google analytics
                "apps.web.context_processors.google_analytics_id",
            ],
            "loaders": _DEFAULT_LOADERS if DEBUG else _CACHED_LOADERS,
        },
    },
]

WSGI_APPLICATION = "poromics.wsgi.application"

FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# Database
# https://docs.djangoproject.com/en/stable/ref/settings/#databases

if "DATABASE_URL" in env:
    DATABASES = {"default": env.db()}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DJANGO_DATABASE_NAME", default="poromics"),
            "USER": env("DJANGO_DATABASE_USER", default="postgres"),
            "PASSWORD": env("DJANGO_DATABASE_PASSWORD", default="***"),
            "HOST": env("DJANGO_DATABASE_HOST", default="localhost"),
            "PORT": env("DJANGO_DATABASE_PORT", default="5432"),
        }
    }

# Auth and Login

# Django recommends overriding the user model even if you don"t think you need to because it makes
# future changes much easier.
AUTH_USER_MODEL = "users.CustomUser"
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "/"

# Password validation
# https://docs.djangoproject.com/en/stable/ref/settings/#auth-password-validators

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

# Allauth setup

ACCOUNT_ADAPTER = "apps.teams.adapter.AcceptInvitationAdapter"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*"]

ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
ACCOUNT_EMAIL_UNKNOWN_ACCOUNTS = False  # don't send "forgot password" emails to unknown accounts
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
ACCOUNT_UNIQUE_EMAIL = True
# This configures a honeypot field to prevent bots from signing up.
# The ID strikes a balance of "realistic" - to catch bots,
# and "not too common" - to not trip auto-complete in browsers.
# You can change the ID or remove it entirely to disable the honeypot.
ACCOUNT_SIGNUP_FORM_HONEYPOT_FIELD = "phone_number_x"
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_LOGOUT_ON_GET = True
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_USER_DISPLAY = lambda user: user.get_display_name()  # noqa: E731

ACCOUNT_FORMS = {
    "signup": "apps.teams.forms.TeamSignupForm",
}
SOCIALACCOUNT_FORMS = {
    "signup": "apps.users.forms.CustomSocialSignupForm",
}

# User signup configuration: change to "mandatory" to require users to confirm email before signing in.
# or "optional" to send confirmation emails but not require them
ACCOUNT_EMAIL_VERIFICATION = env("ACCOUNT_EMAIL_VERIFICATION", default="none")

AUTHENTICATION_BACKENDS = (
    # Needed to login by username in Django admin, regardless of `allauth`
    "django.contrib.auth.backends.ModelBackend",
    # `allauth` specific authentication methods, such as login by e-mail
    "allauth.account.auth_backends.AuthenticationBackend",
)

# enable social login
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APPS": [
            {
                "client_id": env("GOOGLE_CLIENT_ID", default=""),
                "secret": env("GOOGLE_SECRET_ID", default=""),
                "key": "",
            },
        ],
        "SCOPE": [
            "profile",
            "email",
        ],
        "AUTH_PARAMS": {
            "access_type": "online",
        },
    },
    "github": {
        "APPS": [
            {
                "client_id": env("GITHUB_CLIENT_ID", default=""),
                "secret": env("GITHUB_SECRET_ID", default=""),
                "key": "",
            },
        ],
        "SCOPE": [
            "user",
        ],
    },
}

# For turnstile captchas
TURNSTILE_KEY = env("TURNSTILE_KEY", default=None)
TURNSTILE_SECRET = env("TURNSTILE_SECRET", default=None)


# Internationalization
# https://docs.djangoproject.com/en/stable/topics/i18n/

LANGUAGE_CODE = "en-us"
LANGUAGE_COOKIE_NAME = "poromics_language"
LANGUAGES = [
    ("en", gettext_lazy("English")),
    ("fr", gettext_lazy("French")),
]
LOCALE_PATHS = (BASE_DIR / "locale",)

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/stable/howto/static-files/

STATIC_ROOT = BASE_DIR / "static_root"
STATIC_URL = "/static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        # swap these to use manifest storage to bust cache when files change
        # note: this may break image references in sass/css files which is why it is not enabled by default
        # "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"

USE_S3_MEDIA = env.bool("USE_S3_MEDIA", default=False)
if USE_S3_MEDIA:
    # Media file storage in S3
    # Using this will require configuration of the S3 bucket
    # See https://docs.saaspegasus.com/configuration/#storing-media-files
    AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
    AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
    AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="poromics-media")
    AWS_S3_CUSTOM_DOMAIN = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"
    PUBLIC_MEDIA_LOCATION = "media"
    MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/{PUBLIC_MEDIA_LOCATION}/"
    STORAGES["default"] = {
        "BACKEND": "apps.web.storage_backends.PublicMediaStorage",
    }

# Vite Integration
DJANGO_VITE = {
    "default": {
        "dev_mode": env.bool("DJANGO_VITE_DEV_MODE", default=DEBUG),
        "dev_server_host": env("DJANGO_VITE_HOST", default="localhost"),
        "dev_server_port": env.int("DJANGO_VITE_PORT", default=5173),
        "manifest_path": BASE_DIR / "static" / ".vite" / "manifest.json",
    }
}

# Default primary key field type
# https://docs.djangoproject.com/en/stable/ref/settings/#default-auto-field

# future versions of Django will use BigAutoField as the default, but it can result in unwanted library
# migration files being generated, so we stick with AutoField for now.
# change this to BigAutoField if you"re sure you want to use it and aren"t worried about migrations.
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# Removes deprecation warning for future compatibility.
# see https://adamj.eu/tech/2023/12/07/django-fix-urlfield-assume-scheme-warnings/ for details.
FORMS_URLFIELD_ASSUME_HTTPS = True

# Email setup

# default email used by your server
SERVER_EMAIL = env("SERVER_EMAIL", default="noreply@localhost:8000")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="jgostick@gmail.com")

# The default value will print emails to the console, but you can change that here
# and in your environment.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")

# Most production backends will require further customization. The below example uses Mailgun.
# ANYMAIL = {
#     "MAILGUN_API_KEY": env("MAILGUN_API_KEY", default=None),
#     "MAILGUN_SENDER_DOMAIN": env("MAILGUN_SENDER_DOMAIN", default=None),
# }

# use in production
# see https://github.com/anymail/django-anymail for more details/examples
# EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"

EMAIL_SUBJECT_PREFIX = "[Poromics] "

# Django sites

SITE_ID = 1

# DRF config
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ("apps.api.permissions.IsAuthenticatedOrHasUserAPIKey",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
}


SPECTACULAR_SETTINGS = {
    "TITLE": "Poromics",
    "DESCRIPTION": "Network extraction as a service",  # noqa: E501
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SWAGGER_UI_SETTINGS": {
        "displayOperationId": True,
    },
    "PREPROCESSING_HOOKS": [
        "apps.api.schema.filter_schema_apis",
    ],
    "APPEND_COMPONENTS": {
        "securitySchemes": {"ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "Authorization"}}
    },
    "SECURITY": [
        {
            "ApiKeyAuth": [],
        }
    ],
}
# Redis, cache, and/or Celery setup
if "REDIS_URL" in env:
    REDIS_URL = env("REDIS_URL")
elif "REDIS_TLS_URL" in env:
    REDIS_URL = env("REDIS_TLS_URL")
else:
    REDIS_HOST = env("REDIS_HOST", default="localhost")
    REDIS_PORT = env("REDIS_PORT", default="6379")
    REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"

if REDIS_URL.startswith("rediss"):
    REDIS_URL = f"{REDIS_URL}"

DUMMY_CACHE = {
    "BACKEND": "django.core.cache.backends.dummy.DummyCache",
}
REDIS_CACHE = {
    "BACKEND": "django.core.cache.backends.redis.RedisCache",
    "LOCATION": REDIS_URL,
}
CACHES = {
    "default": DUMMY_CACHE if DEBUG else REDIS_CACHE,
}

# Central queue catalog
QUEUE_CATALOG_PATH = env("QUEUE_CATALOG_PATH", default=str(default_catalog_path()))
try:
    QUEUE_CATALOG = load_queue_catalog(QUEUE_CATALOG_PATH)
except QueueCatalogError as exc:
    raise ImproperlyConfigured(f"Invalid queue catalog at {QUEUE_CATALOG_PATH}: {exc}") from exc


def _first_catalog_endpoint(compute_system: str, fallback: str = "") -> str:
    for queue in QUEUE_CATALOG.get("queues", []):
        if queue.get("enabled") and queue.get("compute_system") == compute_system:
            endpoint = str(queue.get("endpoint_url") or "").strip()
            if endpoint:
                return endpoint
    return fallback


def _parse_queue_endpoint_pairs(raw_pairs: list[str]) -> dict[str, str]:
    """Parse QUEUE=URL strings from env into a queue-to-endpoint mapping."""
    mapping: dict[str, str] = {}
    for pair in raw_pairs:
        item = pair.strip()
        if not item or "=" not in item:
            continue
        queue_name, endpoint_url = item.split("=", 1)
        queue_name = queue_name.strip()
        endpoint_url = endpoint_url.strip()
        if queue_name and endpoint_url:
            mapping[queue_name] = endpoint_url
    return mapping


def _queue_names_for_compute(compute_system: str) -> list[str]:
    names: list[str] = []
    for queue in QUEUE_CATALOG.get("queues", []):
        if queue.get("enabled") and queue.get("compute_system") == compute_system:
            names.append(str(queue["name"]))
    return names


# Julia tortuosity service routing
JULIA_SERVER_HOST = env("JULIA_SERVER_HOST", default="127.0.0.1")
JULIA_SERVER_PORT = env("JULIA_SERVER_PORT", default="2999")
_JULIA_FALLBACK_URL = f"http://{JULIA_SERVER_HOST}:{JULIA_SERVER_PORT}"
JULIA_DEFAULT_SERVER_URL = env(
    "JULIA_DEFAULT_SERVER_URL",
    default=_first_catalog_endpoint("julia", fallback=_JULIA_FALLBACK_URL),
)

JULIA_BACKEND_QUEUE_MAP = build_backend_queue_map(QUEUE_CATALOG, "julia")
if not JULIA_BACKEND_QUEUE_MAP:
    raise ImproperlyConfigured("Queue catalog must define at least one enabled Julia queue.")

JULIA_QUEUE_ENDPOINTS = build_queue_endpoint_map(QUEUE_CATALOG, "julia")
JULIA_QUEUE_ENDPOINTS.update(_parse_queue_endpoint_pairs(env.list("JULIA_QUEUE_ENDPOINTS", default=[])))

for _queue_name in _queue_names_for_compute("julia"):
    JULIA_QUEUE_ENDPOINTS.setdefault(_queue_name, JULIA_DEFAULT_SERVER_URL)

# Taichi permeability service routing
# Empty default keeps existing local in-process Taichi execution.
TAICHI_DEFAULT_SERVER_URL = env(
    "TAICHI_DEFAULT_SERVER_URL",
    default=_first_catalog_endpoint("taichi", fallback=""),
)

TAICHI_BACKEND_QUEUE_MAP = build_backend_queue_map(QUEUE_CATALOG, "taichi")
if not TAICHI_BACKEND_QUEUE_MAP:
    raise ImproperlyConfigured("Queue catalog must define at least one enabled Taichi queue.")

TAICHI_QUEUE_ENDPOINTS = build_queue_endpoint_map(QUEUE_CATALOG, "taichi")
TAICHI_QUEUE_ENDPOINTS.update(_parse_queue_endpoint_pairs(env.list("TAICHI_QUEUE_ENDPOINTS", default=[])))

if TAICHI_DEFAULT_SERVER_URL:
    for _queue_name in _queue_names_for_compute("taichi"):
        TAICHI_QUEUE_ENDPOINTS.setdefault(_queue_name, TAICHI_DEFAULT_SERVER_URL)

# Generic Python remote analysis service routing (for compute_system=cpu queues).
PYTHON_REMOTE_DEFAULT_SERVER_URL = env(
    "PYTHON_REMOTE_DEFAULT_SERVER_URL",
    default=_first_catalog_endpoint("cpu", fallback=""),
)
PYTHON_REMOTE_QUEUE_ENDPOINTS = build_queue_endpoint_map(QUEUE_CATALOG, "cpu")
PYTHON_REMOTE_QUEUE_ENDPOINTS.update(_parse_queue_endpoint_pairs(env.list("PYTHON_REMOTE_QUEUE_ENDPOINTS", default=[])))

if PYTHON_REMOTE_DEFAULT_SERVER_URL:
    for _queue_name in _queue_names_for_compute("cpu"):
        PYTHON_REMOTE_QUEUE_ENDPOINTS.setdefault(_queue_name, PYTHON_REMOTE_DEFAULT_SERVER_URL)

# RunPod Pod lifecycle controls (shared across dashboard and workers).
RUNPOD_API_BASE_URL = env("RUNPOD_API_BASE_URL", default="https://rest.runpod.io/v1")
RUNPOD_API_KEY = env("RUNPOD_API_KEY", default="")
RUNPOD_DEFAULT_CLOUD_TYPE = env("RUNPOD_DEFAULT_CLOUD_TYPE", default="SECURE")
RUNPOD_DEFAULT_COMPUTE_TYPE = env("RUNPOD_DEFAULT_COMPUTE_TYPE", default="GPU")
RUNPOD_DEFAULT_PORTS = env.list("RUNPOD_DEFAULT_PORTS", default=["8888/http", "22/tcp"])
RUNPOD_REGISTRY_AUTH_ID = env("RUNPOD_REGISTRY_AUTH_ID", default="")
RUNPOD_REGISTRY_USERNAME = env("RUNPOD_REGISTRY_USERNAME", default="")
RUNPOD_REGISTRY_PAT = env("RUNPOD_REGISTRY_PAT", default="")

RUNPOD_CONNECT_TIMEOUT_SECONDS = env.float("RUNPOD_CONNECT_TIMEOUT_SECONDS", default=5.0)
RUNPOD_HTTP_TIMEOUT_SECONDS = env.float("RUNPOD_HTTP_TIMEOUT_SECONDS", default=20.0)
RUNPOD_RETRY_COUNT = env.int("RUNPOD_RETRY_COUNT", default=2)
RUNPOD_RETRY_BACKOFF_SECONDS = env.float("RUNPOD_RETRY_BACKOFF_SECONDS", default=0.5)
RUNPOD_OPTIONS_CACHE_TTL_SECONDS = env.int("RUNPOD_OPTIONS_CACHE_TTL_SECONDS", default=900)
RUNPOD_IDEMPOTENCY_TTL_SECONDS = env.int("RUNPOD_IDEMPOTENCY_TTL_SECONDS", default=600)
RUNPOD_WORKER_WAKE_ENABLED = env.bool("RUNPOD_WORKER_WAKE_ENABLED", default=False)
RUNPOD_QUEUE_POD_IDS = _parse_queue_endpoint_pairs(env.list("RUNPOD_QUEUE_POD_IDS", default=[]))
RUNPOD_WAKE_TIMEOUT_SECONDS = env.float("RUNPOD_WAKE_TIMEOUT_SECONDS", default=300.0)
RUNPOD_WAKE_POLL_INTERVAL_SECONDS = env.float("RUNPOD_WAKE_POLL_INTERVAL_SECONDS", default=5.0)

ANALYSIS_DEFAULT_QUEUE_MAP = dict(QUEUE_CATALOG.get("analysis_defaults", {}))

CELERY_BROKER_URL = CELERY_RESULT_BACKEND = REDIS_URL
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Add tasks to this dict and run `python manage.py bootstrap_celery_tasks` to create them
SCHEDULED_TASKS: dict[str, Any] = {
    "test-celerybeat": {
        "task": "pegasus.apps.examples.tasks.example_log_task",
        "schedule": 60,
        "expire_seconds": 60,
    },
    # Example of a crontab schedule
    # from celery import schedules
    # "daily-4am-task": {
    #     "task": "some.task.path",
    #     "schedule": schedules.crontab(minute=0, hour=4),
    # },
}

# Channels / Daphne setup

ASGI_APPLICATION = "poromics.asgi.application"
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
        },
    },
}

# Health Checks
# A list of tokens that can be used to access the health check endpoint
HEALTH_CHECK_TOKENS = env.list("HEALTH_CHECK_TOKENS", default="")

# Waffle config

WAFFLE_FLAG_MODEL = "teams.Flag"

# Pegasus config

# replace any values below with specifics for your project
PROJECT_METADATA = {
    "NAME": gettext_lazy("Poromics"),
    "URL": "http://localhost:8000",
    "DESCRIPTION": gettext_lazy("Network extraction as a service"),  # noqa: E501
    "IMAGE": "https://upload.wikimedia.org/wikipedia/commons/2/20/PEO-pegasus_black.svg",
    "KEYWORDS": "SaaS, django",
    "CONTACT_EMAIL": "jgostick@gmail.com",
}

# set this to True in production to have URLs generated with https instead of http
USE_HTTPS_IN_ABSOLUTE_URLS = env.bool("USE_HTTPS_IN_ABSOLUTE_URLS", default=False)

ADMINS = ["jgostick@gmail.com"]

# Add your google analytics ID to the environment to connect to Google Analytics
GOOGLE_ANALYTICS_ID = env("GOOGLE_ANALYTICS_ID", default="")

# these daisyui themes are used to set the dark and light themes for the site
# they must be valid themes included in your tailwind.config.js file.
# more here: https://daisyui.com/docs/themes/
LIGHT_THEME = "light"
DARK_THEME = "dark"


# Sentry setup

# populate this to configure sentry. should take the form: "https://****@sentry.io/12345"
SENTRY_DSN = env("SENTRY_DSN", default="")


if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
    )

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": '[{asctime}] {levelname} "{name}" {message}',
            "style": "{",
            "datefmt": "%d/%b/%Y %H:%M:%S",  # match Django server time format
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": env("DJANGO_LOG_LEVEL", default="INFO"),
        },
        "poromics": {
            "handlers": ["console"],
            "level": env("POROMICS_LOG_LEVEL", default="INFO"),
        },
        "pegasus": {
            "handlers": ["console"],
            "level": env("PEGASUS_LOG_LEVEL", default="DEBUG"),
        },
        "apps.pore_analysis": {
            "handlers": ["console"],
            "level": "DEBUG",
        },
    },
}
