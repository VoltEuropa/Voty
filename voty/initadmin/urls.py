# ==============================================================================
# Voty initadmin urls
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------
from django.conf.urls import url, include
from django.views.generic.base import TemplateView
from django.contrib import admin
from django.utils.translation import ugettext as _

import notifications.urls

from . import views

urlpatterns = [

  # autocomplete for signup codes
  url(r"^signupcode_autocomplete$", views.SignupCodeAutocomplete.as_view(), name="signupcode_autocomplete"),

  # all users
  url(r"^account/", include("account.urls")),
  url(r"^account/edit$", views.profile_edit, name="profile_edit"),
  url(r"^account/signup/$", views.LoginView.as_view(), name="account_signup"),

  url(r"^avatar/", include("avatar.urls")),
  url(r"^worklist/notifications/", include(notifications.urls, namespace="notifications")),
  url(r"^worklist/notifications/", include("pinax.notifications.urls")),
  url(r"^worklist/notifications/$", views.notification_list, name="notifications"),

  # moderators
  url(r"^backoffice/users/$", views.user_list, name="users"),
  url(r"^backoffice/users/(?P<user_id>.*)/?$", views.user_view, name="user_moderate"),
  url(r"^backoffice/invite/", views.user_invite, name="user_invite"),
  url(r"^backoffice/initiatives/", views.initiative_list, name="initiatives"),
  url(r"^backoffice/download/(?P<batch_id>.*)$", views.download_csv, name="download_user_batch_invite"),
  url(r"^backoffice/delete/(?P<batch_id>.*)$", views.delete_csv, name="delete_user_batch_invite"),

  # notification forward to user
  url(r"^backoffice/users/(?P<user_id>\d+)/?$", views.user_view, name=_("user")),

  # superusers
  url(r"^admin/", admin.site.urls),
]
