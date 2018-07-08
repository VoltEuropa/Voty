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
from six.moves import configparser

site_parser = configparser.ConfigParser()
site_parser.read(os.path.join(settings.BASE_DIR, "init.ini"))

register = template.Library()

# call: {% load site_defaults %} then call {{ [setting_name]|get_setting %}
@register.filter
@stringfilter
def get_setting(my_setting):
  return site_parser.get("settings", my_setting)
