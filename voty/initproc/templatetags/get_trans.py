# -*- coding: utf-8 -*-
# ==============================================================================
# Translate text from .ini file
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

# using makemessage -e=...,.ini texts can be labelled for translation and 
# included in the .po/.mo files. however they do not get translated, because 
# the text is imported {% trans "text" %} and placed in a template like this.
# so we do it here.
from django import template
from django.template.defaultfilters import stringfilter
from django.utils.translation import ugettext as _

import re

register = template.Library()
snip_start = '{% trans "'
snip_end = '" %}'

# call: {% load get_trans %} then call {{ [tag]|get_setting %}
@register.filter
@stringfilter
def get_trans(translation_tag):
  if translation_tag.find(snip_start) > -1:
    return _(translation_tag.partition('{% trans "')[2].partition('" %}')[0])
  return _(translation_tag)
