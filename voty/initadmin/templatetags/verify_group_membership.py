# -*- coding: utf-8 -*-
# ==============================================================================
# Voty bouncer to check group membership in template
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

# https://docs.djangoproject.com/en/2.0/howto/custom-template-tags/
# https://docs.djangoproject.com/en/dev/topics/settings/#custom-default-settings

from django import template
from django.conf import settings

register = template.Library()

# call: {% if request.user|has_group:"[group-name]" %}
@register.filter("has_group")
def has_group(user, settings_group_lookup_key):
  groups = user.groups.all().values_list("name", flat=True)

  # XXX lame to pass key, but I couldn't get has_group with getSetting to work
  candidate_list = ["{0}".format(v) for k,v in settings.PLATFORM_GROUP_VALUE_LIST.items() if not k.startswith("__")]
  return True if any(group in candidate_list for group in groups) else False
