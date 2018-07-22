# -*- coding: utf-8 -*-
# ==============================================================================
# Templify a parameter so it can be wrapped in a {% %} tag
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

# https://docs.djangoproject.com/en/2.0/howto/custom-template-tags/

import os
from django import template
from django.template.defaultfilters import stringfilter

register = template.Library()

# call: {% load templify %} then call {% [parameter]|templify %}
# this returns the template value, if you're stuck with:
# {% url 'some.parameter' %} => {% url some_parameter|templify ... %}
@register.filter
@stringfilter
def templify(my_param):
  return str(my_param)
