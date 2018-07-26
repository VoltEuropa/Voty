# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initadmin Management commands
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

from django.core.management import BaseCommand
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Group, Permission, User
from django.contrib.auth import models as auth_models
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from django.utils.translation import ugettext as _

from pinax.notifications.models import NoticeType

def create_deleted_user():
  try:
    user = User.objects.get(username="deleted")
  except ObjectDoesNotExist:
    User.objects.create_user(
      username="deleted",
      first_name="Deleted",
      last_name="User",
      is_active=False,
      is_staff=True,
    )

# translations in apps.py are recorded but the translated texts do not make it 
# into pinax. Maybe from here.
# Pinax requires noticetypes to be stored in the database with title and 
# description. 
def create_notice_types(**kwargs):

  # Moderations
  for key, command in vars(settings.NOTIFICATIONS.MODERATE).items():
    NoticeType.create(
      command,
      getattr(settings.NOTIFICATIONS.I18N_VALUE_LIST, key),
      getattr(settings.NOTIFICATIONS.I18N_DESCRIPTION_LIST, key),
    )
  
  for key, command in vars(settings.NOTIFICATIONS.INVITE).items():
    NoticeType.create(
      command,
      getattr(settings.NOTIFICATIONS.I18N_VALUE_LIST, key),
      getattr(settings.NOTIFICATIONS.I18N_DESCRIPTION_LIST, key),
    )

  for key, command in vars(settings.NOTIFICATIONS.INITIATIVE).items():
    NoticeType.create(
      command,
      getattr(settings.NOTIFICATIONS.I18N_VALUE_LIST, key),
      getattr(settings.NOTIFICATIONS.I18N_DESCRIPTION_LIST, key),
    )

# BACKCOMPAT (migrations 0025)
# add all staff to the defined backcompat role and vice versa, then remove the 
# backcompat groups again. Used to be in migrations, fails when setting up
# where custom permissions don't exist. Plus, custom groups should be
# configurable, so we replicate what was done here, then switch to configurable
# custom groups and permissions
def create_group(name):

  # returns group, created (True/False)
  return Group.objects.get_or_create(name=name)

def delete_group(name):
  try:
    Group.objects.get(name=name).delete()
  except ObjectDoesNotExist:
    # pass
    raise Exception("initadmin: trying to delete non-existing group")

def get_permission(app, name):
  try:
    return Permission.objects.get(content_type__app_label=app, codename=name)
  except:
    return False

def backcompat_init_teams_and_permissions():
  for group_title in settings.BACKCOMPAT_ROLE_LIST:
    new_group, created = create_group(group_title)

    if created:
      for user in User.objects.filter(is_staff=True, is_active=True):
        user.groups.add(new_group)

      # lazy with app name
      # XXX what about content_type?
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

def create_custom_groups_and_permissions():
  group_list = []
  group_permission_dict = dict([(x, y.split(",")) for x, y in settings.PLATFORM_GROUP_USER_PERMISSION_MAPPING])

  for (group_key, group_title) in settings.PLATFORM_GROUP_LIST:
    new_group, created = create_group(settings.PLATFORM_GROUP_VALUE_LIST[group_key])
    group_list.append((group_key, new_group))
    if created:
      new_group.save()

  for (perm_key, perm_code_model) in settings.PLATFORM_USER_PERMISSION_LIST:
    perm_code, perm_app_model = perm_code_model.split(",")
    perm_name = settings.PLATFORM_USER_PERMISSION_VALUE_LIST[perm_key]

    if Permission.objects.filter(name=perm_name).exists() == False:

      # permission is added to a group, permission pertains to a content-type
      # in this case a user (2) or an initiative (37)
      perm_app, perm_model = perm_app_model.split(".")
      perm = Permission(
        name=perm_name,
        codename=perm_code,
        content_type=ContentType.objects.get(app_label=perm_app, model=perm_model)
      )
      perm.save()

      # XXX a lot of saving groups, find better way
      for group in group_list:
        for group_key, group_permission_list in group_permission_dict.items():
          if group[0] == group_key:
            for group_permission_key in group_permission_list:
              if perm_key == group_permission_key.upper():
                group[1].permissions.add(perm)

  for group in group_list:
    group[1].save()

# ---------------------------------- Command -----------------------------------
class Command(BaseCommand):
  help = "Create groups, permissions and notice types as defined in settings.py"

  def handle(self, *args, **options):
    
    # XXX this doesn't work when setting up from scratch
    # backcompat - move existing staff to custom group and custom group to staff
    backcompat_init_teams_and_permissions()
    backcompat_reverse_teams_and_permissions()
    
    # define custom groups as per init.ini
    create_custom_groups_and_permissions()
    
    # create notice types for PINAX
    create_notice_types()

    # create a deleted-user for keeping contributions from deleted users
    create_deleted_user()

    print("Groups, Permissions, Noticetypes created.")
