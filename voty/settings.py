# -*- coding: utf-8 -*-
# ==============================================================================
# Django settings for Voty project
# ==============================================================================
#
# full settings: https://docs.djangoproject.com/en/1.10/ref/settings/
#
# parameters (*default)
# ------------------------------------------------------------------------------

import os
import dj_database_url
from types import SimpleNamespace
from six.moves import configparser
from django.utils.translation import ugettext_lazy as _

# ------------------------------ helpers ---------------------------------------
def _getCharDict():
  char_dict = {}
  for x in ("#","A","B","C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z"):
    char_dict[x] = {"value": x}
  return char_dict

def _getItemsAsDict(section):
  return dict(raw_parser.items(section))
  
def _strip(snippet):
  return snippet.partition('{% trans "')[2].partition('" %}')[0]

def _getTranslatedSimpleNameSpace(section):
  return SimpleNamespace(**dict([(key, _(_strip(snippet))) for key, snippet in raw_parser._sections[section].items()]))

# ----------------------------- SETTINGS ---------------------------------------
# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.10/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("SECRET", "&v--b40hjwtfre(o^(4=-s!g7!x&za1u_=v#140ex+_%iek(c#");

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Retrieve initialization configuration, use raw parser i18n-texts
raw_parser = configparser.RawConfigParser()
raw_parser.optionxform=str
raw_parser.read(os.path.join(BASE_DIR, "init.ini"))

DEBUG = not os.environ.get("VIRTUAL_HOST", False)

ALLOWED_HOSTS = os.environ.get("VIRTUAL_HOST", raw_parser.get("settings", "VIRTUAL_HOST_LIST")).split(",")

INSTALLED_APPS = [
  "django.contrib.auth",
  "django.contrib.sites",
  "django.contrib.contenttypes",
  "django.contrib.sessions",
  "django.contrib.messages",
  "django.contrib.staticfiles",
  "django.contrib.postgres",

  # 3rd party
  "account",
  "avatar",
  "mathfilters",
  "mailer",
  "pinax.notifications",
  "notifications",
  "bootstrapform",
  "fullurl",
  "django_ajax",
  "reversion",
  "corsheaders",

  # must be before admin ...
  "dal",
  "dal_select2",
  "django.contrib.admin",

  # locally
  "voty.initadmin",
  "voty.initproc",
]

MIDDLEWARE = [
  "django.middleware.security.SecurityMiddleware",
  "django.contrib.sessions.middleware.SessionMiddleware",
  "corsheaders.middleware.CorsMiddleware",
  "django.middleware.locale.LocaleMiddleware",
  "django.middleware.common.CommonMiddleware",
  "django.middleware.csrf.CsrfViewMiddleware",
  "django.contrib.auth.middleware.AuthenticationMiddleware",
  "voty.initproc.guard.add_guard",
  "voty.initadmin.notify_backend.mark_as_read",
  "django.contrib.messages.middleware.MessageMiddleware",
  "django.middleware.clickjacking.XFrameOptionsMiddleware",
  "account.middleware.TimezoneMiddleware"
]

PINAX_NOTIFICATIONS_BACKENDS = [
  ("site", "voty.initadmin.notify_backend.SiteBackend"),
  ("email", "pinax.notifications.backends.email.EmailBackend"),
]

LOGGING = {
  "version": 1,
  "disable_existing_loggers": False,
  "handlers": {
    "console": {
      "class": "logging.StreamHandler",
    },
  },
  "loggers": {
    "django": {
      "handlers": ["console"],
      "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
    },
  },
}

AUTHENTICATION_BACKENDS = (
  "account.auth_backends.EmailAuthenticationBackend",
  "django.contrib.auth.backends.ModelBackend",
)

ROOT_URLCONF = "voty.urls"
LOGIN_URL = "/account/login/"
LOGIN_REDIRECT_URL = "/"

TEMPLATES = [{
  "BACKEND": "django.template.backends.django.DjangoTemplates",
  "DIRS": [
    os.path.join(BASE_DIR, "templates")
  ],
  "APP_DIRS": True,
  "OPTIONS": {
    "context_processors": [
      "django.template.context_processors.debug",
      "django.template.context_processors.request",
      "django.template.context_processors.i18n",
      "django.contrib.auth.context_processors.auth",
      "django.contrib.messages.context_processors.messages",
      "account.context_processors.account",
    ],
  },
},]

WSGI_APPLICATION = "voty.wsgi.application"

SITE_ID = 1

# Database
# https://docs.djangoproject.com/en/1.10/ref/settings/#databases

DATABASES = {
  "default": dj_database_url.config(default="sqlite://./db.sqlite3")
}


# Password validation
# https://docs.djangoproject.com/en/1.10/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
  {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",},
  {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",},
  {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",},
  {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",},
]

# Internationalization
USE_I18N = True
USE_L10N = True
USE_TZ = True

LOCALE_PATHS = (
  os.path.join( BASE_DIR, "locale"),
)

ACCOUNT_LANGUAGES = tuple([(x[0], _(_strip(x[1]))) for x in raw_parser.items("alternative_language_list")])
LANGUAGE_CODE = raw_parser.get("settings", "DEFAULT_LANGUAGE")
TIME_ZONE = raw_parser.get("settings", "DEFAULT_TIMEZONE")
LANGUAGES = ACCOUNT_LANGUAGES

# not sure which one?
NOTIFICATIONS_USE_JSONFIELD=True
DJANGO_NOTIFICATIONS_CONFIG = { 'USE_JSONFIELD': True}

ACCOUNT_EMAIL_UNIQUE = True
ACCOUNT_OPEN_SIGNUP = False
AVATAR_GRAVATAR_DEFAULT = "retro"

DEFAULT_FROM_EMAIL = raw_parser.get("settings", "DEFAULT_FROM_EMAIL")
EMAIL_BACKEND = "mailer.backend.DbBackend"

if DEBUG:
  EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
  EMAIL_HOST = "localhost"
  EMAIL_PORT = 1025
elif os.environ.get("SPARKPOST_API_KEY", None):
  SPARKPOST_API_KEY = os.environ.get("SPARKPOST_API_KEY")
  MAILER_EMAIL_BACKEND = "sparkpost.django.email_backend.SparkPostEmailBackend"
  SPARKPOST_OPTIONS = {
    "track_opens": False,
    "track_clicks": False,
    "transactional": True,
  }
else:
  MAILER_EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
  EMAIL_USE_TLS = True
  EMAIL_HOST = os.environ.get("SMTP_SERVER", "smtp.mailgun.org")
  EMAIL_HOST_USER = os.environ.get("SMTP_USERNAME", "mymail@gmail.com")
  EMAIL_HOST_PASSWORD = os.environ.get("SMTP_PASSWORD", "password")
  EMAIL_PORT = int(os.environ.get("SMTP_PORT", 587))


from django.contrib import messages

MESSAGE_TAGS = {
  messages.ERROR: "danger"
}

# What we allow in the editor
MARKDOWN_FILTER_WHITELIST_TAGS = ["a", "p", "b", "br", "em", "strong", "i", "code", "pre", "blockquote", "ul", "ol", "li"]

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.10/howto/static-files/

STATIC_URL = "/static/"
MEDIA_URL = "/media/"

STATICFILES_DIRS = (

  # Put strings here, like "/home/html/static" or "C:/www/django/static".
  # Always use forward slashes, even on Windows.
  # Don"t forget to use absolute paths, not relative paths.
  os.path.join( BASE_DIR, "static"),
)

STATIC_ROOT = os.path.join( BASE_DIR, "public", "static")
MEDIA_ROOT = os.path.join( BASE_DIR, "public", "media")

# CORS
CORS_ORIGIN_WHITELIST = tuple(raw_parser.get("settings", "CORS_ORIGIN_WHITELIST").split(","))
CORS_ALLOW_CREDENTIALS = True

# ----------------------------- Customizations ---------------------------------
# XXX don't use _sections => {s:dict(config.items(s)) for s in config.sections()}
DEFAULT_LANGUAGE = raw_parser.get("settings", "DEFAULT_LANGUAGE")
DEFAULT_CONTACT_EMAIL = raw_parser.get("settings", "DEFAULT_CONTACT_EMAIL")
THEME_CONTACT_EMAIL = raw_parser.get("settings", "THEME_CONTACT_EMAIL")
INITIATIVE_SUPPORT_EMAIL = raw_parser.get("settings", "INITIATIVE_SUPPORT_EMAIL")
MIN_SEARCH_LENGTH = raw_parser.get("settings", "MIN_SEARCH_LENGTH")
URL_HOWTO_INITIATIVE = raw_parser.get("settings", "URL_HOWTO_INITIATIVE")

ACCOUNT_DELETION_EXPUNGE_HOURS = raw_parser.get("settings", "ACCOUNT_DELETION_EXPUNGE_HOURS")
PLATFORM_TITLE = raw_parser.get("settings", "PLATFORM_TITLE")
PLATFORM_SUB_TITLE = raw_parser.get("settings", "PLATFORM_SUB_TITLE")
PLATFORM_TITLE_ACRONYM = raw_parser.get("settings", "PLATFORM_TITLE_ACRONYM")

PLATFORM_DEFAULT_URL = raw_parser.get("settings", "PLATFORM_DEFAULT_URL")
PLATFORM_MARKETPLACE_URL = raw_parser.get("settings", "PLATFORM_MARKETPLACE_URL")
PLATFORM_REGISTRATION_URL = raw_parser.get("settings", "PLATFORM_REGISTRATION_URL")
PLATFORM_LEGAL_URL = raw_parser.get("settings", "PLATFORM_LEGAL_URL")
PLATFORM_DATA_PROTECTION_URL = raw_parser.get("settings", "PLATFORM_DATA_PROTECTION_URL")
INITIATIVE_TEMPLATE_URL = raw_parser.get("settings", "INITIATIVE_TEMPLATE_URL")
INITIATIVE_EXPLANATION_URL = raw_parser.get("settings", "INITIATIVE_EXPLANATION_URL")
PLATFORM_VOTING_REGULATION_URL = raw_parser.get("settings", "PLATFORM_VOTING_REGULATION_URL")
PLATFORM_TECH_DEVELOPMENT_URL = raw_parser.get("settings", "PLATFORM_TECH_DEVELOPMENT_URL")
PLATFORM_TECH_SUPPORT_URL = raw_parser.get("settings", "PLATFORM_TECH_SUPPORT_URL")
PLATFORM_TECH_SOURCE_CODE_URL = raw_parser.get("settings", "PLATFORM_TECH_SOURCE_CODE_URL")
PLATFORM_TECH_DEVELOPMENT_TICKET_URL = raw_parser.get("settings", "PLATFORM_TECH_DEVELOPMENT_TICKET_URL")
PLATFORM_SOCIAL_MEDIA_LOGO_URL = raw_parser.get("settings", "PLATFORM_SOCIAL_MEDIA_LOGO_URL")
PLATFORM_LOGO_URL = raw_parser.get("settings", "PLATFORM_LOGO_URL")

SITE_FONT_CSS_URL = raw_parser.get("settings", "SITE_FONT_CSS_URL")
SITE_THEME_CSS_URL = raw_parser.get("settings", "SITE_THEME_CSS_URL")
SITE_JS_URL = raw_parser.get("settings", "SITE_JS_URL")

# XXX why do those have to be classes? Nothing will ever change.
VOTED = raw_parser._sections["initiative_vote_state_list"]

# platform options
USE_UNIQUE_EMAILS = raw_parser.get("settings", "USER_USE_UNIQUE_EMAILS")
USE_DIVERSE_MODERATION_TEAM = raw_parser.get("settings", "USER_USE_DIVERSE_MODERATION_TEAM")

# moderation
MODERATIONS = SimpleNamespace(**raw_parser._sections["moderation_setting_list"])

# groups and permissions
BACKCOMPAT_ROLE_LIST = raw_parser.get("settings", "PLATFORM_BACKCOMPAT_GROUP_LIST").split(",")
BACKCOMPAT_PERMISSION_LIST = raw_parser.get("settings", "PLATFORM_BACKCOMPAT_PERMISSION_LIST").split(",")

PLATFORM_GROUP_LIST = raw_parser.items("platform_group_list")
PLATFORM_GROUP_VALUE_LIST = raw_parser._sections["platform_group_value_list"]
PLATFORM_GROUP_VALUE_TITLE_LIST = ["{0}".format(v) for k,v in PLATFORM_GROUP_VALUE_LIST.items() if not k.startswith("__")]
PLATFORM_USER_PERMISSION_LIST = raw_parser.items("platform_user_permission_list")
PLATFORM_USER_PERMISSION_VALUE_LIST = raw_parser._sections["platform_user_permission_value_list"]
PLATFORM_GROUP_USER_PERMISSION_MAPPING = raw_parser.items("platform_group_user_permission_mapping")
PLATFORM_NOTIFICATION_RESTRICTED_STATE_PERMISSION_MAPPING = SimpleNamespace(**raw_parser._sections["notification_restricted_state_permission_mapping_list"])

# notifications
# cannot be translated here because python translation objects cannot be stored 
# in the database and pinax stores titles and descriptions in noticetypes. 
# => requires lazy translation whenever displayed
NOTIFICATIONS = SimpleNamespace(**{
  "RESTRICTED": SimpleNamespace(**raw_parser._sections["notification_restricted_state_list"]),
  "PUBLIC": SimpleNamespace(**raw_parser._sections["notification_public_state_list"]),

  # translation lookup values across all notifications
  "I18N_VALUE_LIST": _getTranslatedSimpleNameSpace("notification_i18n_value_list"),
  "I18N_DESCRIPTION_LIST": _getTranslatedSimpleNameSpace("notification_i18n_description_list"),
  "I18N_TODO_TITLE_LIST": _getTranslatedSimpleNameSpace("notification_i18n_todo_list"),
  "I18N_TODO_LIST": [k for k, _ in raw_parser._sections["notification_i18n_todo_list"].items()],
})

# categories
# should all be translated right away because they are only displayed not stored
CATEGORIES = SimpleNamespace(**{
  "SCOPE_CHOICES": [(code_tuple[1], _(_strip(_getItemsAsDict("scope_value_list")[code_tuple[0]]))) for code_tuple in raw_parser.items('scope_list')]
})

# listbox default options
LISTBOX_OPTION_DICT = SimpleNamespace(**{
  "GLOSSARY_CHAR_LIST": _getCharDict(),
  "NUMBER_OF_RECORDS_OPTION_LIST": [("10", "10"), ("20", "20"), ("50", "50"), ("100", "100")],
  "NUMBER_OF_RECORDS_DEFAULT": 2
})


