# -*- coding: utf-8 -*-
# ==============================================================================
# Get a parameter as string so it can be wrapped in a {% %} tag
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

# https://docs.djangoproject.com/en/2.0/howto/custom-template-tags/

import os
from django import template
from django.template.defaultfilters import stringfilter

register = template.Library()

# call: {% load get_as_string %} then call {% [parameter]|get_as_string %}
# this returns the template value, if you're stuck with:
# {% url 'some.parameter' %} gives {% url some_parameter|get_as_string ... %}
@register.filter
@stringfilter
def get_as_string(my_param):
  return str(my_param)

