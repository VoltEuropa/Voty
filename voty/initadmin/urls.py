# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initadmin urls
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------
from django.conf.urls import url, include
from django.views.generic.base import TemplateView
from django.contrib import admin

from . import views

urlpatterns = [

  # all users
  url(r"^account/", include("account.urls")),
  url(r"^avatar/", include("avatar.urls")),
  url(r"^account/edit$", views.profile_edit, name="profile_edit"),
  url(r"^account/login/$", views.LoginView.as_view(), name="account_signup"),
  url(r"^account/language$", TemplateView.as_view(template_name="account/language.html")),
  url(r"^account/delete$", views.profile_delete, name="profile_delete"),
  url(r"^account/localise", views.profile_localise, name="account_localise"),

  # moderators
  url(r"^backoffice/users/$", views.user_list, name="users"),
  url(r"^backoffice/users/(?P<user_id>\d+)/$", views.user_view, name="user_moderate"),
  url(r"^backoffice/invite/", views.user_invite, name="user_invite"),
  url(r"^backoffice/initiatives/", views.initiative_list, name="initiatives"),
  
  # superusers
  url(r"^admin/", admin.site.urls),
]
