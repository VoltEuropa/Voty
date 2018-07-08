# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initadmin Admin
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings

from account.models import SignupCodeResult
from .models import UserConfig

# BACKCOMPAT (migrations 0025)
# add all staff to the defined backcompat role and vice versa, then remove the 
# backcompat groups again. Used to be in migrations, fails when setting up
# where custom permissions don't exist. Plus, custom groups should be
# configurable, so we replicate what was done here, then switch to configurable
# custom groups and permissions
def create_group(name):
  group, created = Group.objects.get_or_create(name=name)
  if created:
    return group
  else:
    return False

def delete_group(name):
  try:
    Group.objects.get(name=name).delete()
  # mh, where to print too
  except ObjectDoesNotExist:
    # pass
    raise Exception("groups.py: trying to delete non-existing group")

def get_permission(app, name):
  try:
    return Permission.objects.get(content_type__app_label=app, codename=name)
  except:
    return False

def backcompat_init_teams_and_permissions():
  for group_title in settings.BACKCOMPAT_ROLE_LIST:
    new_group = create_group(group_title)

    if new_group:
      for user in User.objects.filter(is_staff=True, is_active=True):
        user.groups.add(new_group)

      # lazy with app name
      for permission_name in settings.BACKCOMPAT_PERMISSION_LIST:
        new_permission = get_permission("initproc", permission_name)
        if new_permission:
          new_group.permissions.add(new_permission)

def backcompat_reverse_teams_and_permissions():
  for group_title in settings.BACKCOMPAT_ROLE_LIST:
    for user in User.objects.filter(groups__name=group_title, is_active=True):
      user.is_staff = True
      user.save()
  delete_group(group_title)


# ----------------------------- UserConfigInline -------------------------------
# what is it?
class UserConfigInline(admin.StackedInline):
  model = UserConfig
  can_delete = False
  verbose_name_plural = 'config'

# ------------------------------- UserAdmin ------------------------------------
# Define a new User admin
class UserAdmin(BaseUserAdmin):
  inlines = (UserConfigInline, )

# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.register(SignupCodeResult)
admin.site.register(Permission)

# backcompat - move existing staff to custom group and custom group to staff
backcompat_init_teams_and_permissions()
backcompat_reverse_teams_and_permissions()
