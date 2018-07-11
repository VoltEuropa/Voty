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
@register.filter("is_team_member")
def is_team_member(user):
  return True if any(group in settings.PLATFORM_GROUP_VALUE_TITLE_LIST for group in user.groups.all().values_list("name", flat=True)) else False
