# ==============================================================================
# Voty GLOBAL Url Configuration
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------
# The "urlpatterns" list routes URLs to views. For more information please see:
# https://docs.djangoproject.com/en/1.10/topics/http/urls/

from django.conf.urls import url, include
from django.conf.urls.static import static
from django.views.generic.base import TemplateView
from django.conf.urls.i18n import i18n_patterns
from django.conf import settings

urlpatterns = [

  # required for multi-language
  url(r"^i18n/", include("django.conf.urls.i18n")),

  # required for resetting email
  url('^', include('django.contrib.auth.urls')),
]
urlpatterns += i18n_patterns(
  url(r"", include("voty.initadmin.urls")),
  url(r"^language$", TemplateView.as_view(template_name="account/language.html")),
  url(r"^about", TemplateView.as_view(template_name="static/about.html")),
  url(r"^help", TemplateView.as_view(template_name="static/help.html")),
  url(r"^register", TemplateView.as_view(template_name="static/register.html")),
  url(r"", include("voty.initproc.urls")),
) + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT
) + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

