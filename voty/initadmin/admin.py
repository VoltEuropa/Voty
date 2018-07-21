# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initadmin Admin
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Permission, User, models
#from django.conf import settings

from account.models import SignupCodeResult
from .models import UserConfig

# ----------------------------- UserConfigInline -------------------------------
# https://docs.djangoproject.com/en/2.0/topics/auth/customizing/#extending-the-existing-user-model
class UserConfigInline(admin.StackedInline):
  model = UserConfig
  can_delete = False
  verbose_name_plural = 'config'

# ------------------------------- UserAdmin ------------------------------------
# Define a new User admin
class UserAdmin(BaseUserAdmin):
  inlines = (UserConfigInline, )

# enforce unique emails (https://stackoverflow.com/a/7564331)
#if settings.USE_UNIQUE_EMAILS:
#  User._meta.get_field('email').__dict__['_unique'] = True or User._meta.get_field('email')._unique = True

# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.register(SignupCodeResult)
admin.site.register(Permission)
