# -*- coding: utf-8 -*-
# ==============================================================================
# Using getattr in a template
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

# https://docs.djangoproject.com/en/2.0/howto/custom-template-tags/
# https://docs.djangoproject.com/en/dev/topics/settings/#custom-default-settings

import os
from django.conf import settings
from django import template

register = template.Library()

# call: {% load get_attr %} then call {{ object|get_attr:key }}
# note, this works only on first level settings
@register.filter
def get_attr(my_obj, my_key):
  return my_obj[my_key]

  #if hasattr(my_obj, str(my_key)):
  #  return getattr(my_obj, my_key)
  #elif hasattr(my_obj, 'has_key') and my_obj.has_key(my_key):
  #  return my_obj[my_arg]
  #elif numeric_test.match(str(my_key)) and len(my_obj) > int(my_key):
  #  return my_obj[int(my_key)]
  #else:
  #  return my_obj.get(my_key)

