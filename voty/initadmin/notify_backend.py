# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initadmin notification (Backend handling)
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------
from django.utils.translation import ugettext
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from pinax.notifications.backends.base import BaseBackend
from notifications.signals import notify

# mark all notifications related to initiative passed in request as read
def mark_as_read(get_response):
  def middleware(request):

      response = get_response(request)
      if request.user and request.user.is_authenticated and getattr(request, "initiative", None):
        initiative_type = ContentType.objects.get_for_model(request.initiative)
        q = request.user.notifications.filter(
          Q(actor_content_type=initiative_type, actor_object_id=request.initiative.id) | \
          Q(target_content_type=initiative_type, target_object_id=request.initiative.id)
        ).mark_all_as_read()

      return response

  return middleware

# ---------------------------- SiteBackend -------------------------------------
class SiteBackend(BaseBackend):

  # XXX what's this for?
  spam_sensitivity = 0

  def deliver(self, recipient, sender, notice_type, extra_context):
    notify_kw = {"verb": notice_type.label}
    for x in ['action_object', 'target', 'verb', 'description', 'flag_id']:
      if x in extra_context:
        notify_kw[x] = extra_context[x]

    notify.send(sender, recipient=recipient, **notify_kw)

