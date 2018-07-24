# -*- coding: utf-8 -*-
# ==============================================================================
# Make certain settings from .ini file accessible in templates
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

# https://docs.djangoproject.com/en/2.0/howto/custom-template-tags/
# https://docs.djangoproject.com/en/dev/topics/settings/#custom-default-settings

import os
from django.conf import settings
from django import template
from django.template.defaultfilters import stringfilter

register = template.Library()

# call: {% load get_setting %} then call {{ [setting_name]|get_setting %}
# note, this works only on first level settings
@register.filter
@stringfilter
def get_setting(my_setting):
  lookup_path = [x.upper() for x in my_setting.split(".")]
  if len(lookup_path) > 1:
    reply = settings
    for key in lookup_path:
      reply = getattr(reply, key)
    return reply
  else:
    return getattr(settings, my_setting.upper())
