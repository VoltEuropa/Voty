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
def create_notice_types(**kwargs):

  # Moderations
  NoticeType.create(settings.NOTIFICATIONS.MODERATE.LOCALISED,
                    _("Localisation Request"),
                    _("A user requests a localisation change to be validated."))

  # Invitations
  NoticeType.create(settings.NOTIFICATIONS.INVITE.SEND,
                    _("Invitation to Initiative"),
                    _("You have been invitied to a new Initiative"))
  NoticeType.create(settings.NOTIFICATIONS.INVITE.ACCEPTED,
                    _("Invitation accepted"),
                    _("The Invitation was accepted"))
  NoticeType.create(settings.NOTIFICATIONS.INVITE.REJECTED,
                    _("Invitation declined"),
                    _("The Invitation was declined"))

  # Initiative
  NoticeType.create(settings.NOTIFICATIONS.INITIATIVE.EDITED,
                    _("Initiative modified"),
                    _("The Initiative was modified"))
  NoticeType.create(settings.NOTIFICATIONS.INITIATIVE.SUBMITTED,
                    _("Initiative submitted"),
                    _("The Initiative was submitted"))
  NoticeType.create(settings.NOTIFICATIONS.INITIATIVE.PUBLISHED,
                    _("Initiative published"),
                    _("The Initiative was published"))
  NoticeType.create(settings.NOTIFICATIONS.INITIATIVE.WENT_TO_DISCUSSION,
                    _("Initiative in discussion"),
                    _("The Initiative has been moved to the discussion phase"))
  NoticeType.create(settings.NOTIFICATIONS.INITIATIVE.DISCUSSION_CLOSED,
                    _("Discussion for Initiative ended"),
                    _("The Initiative can now be finally modified"))
  NoticeType.create(settings.NOTIFICATIONS.INITIATIVE.WENT_TO_VOTE,
                    _("Initiative in Vote"),
                    _("The Initiative has been put to Vote"))

  # Discussion
  NoticeType.create(settings.NOTIFICATIONS.INITIATIVE.NEW_ARGUMENT,
                    _("New Argument in Discussion for Initiative"),
                    _("A new Argument was postet in the Discussion for the Initiative"))

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
  for (group_key, group_title) in settings.PLATFORM_GROUP_LIST:
    new_group, created = create_group(settings.PLATFORM_GROUP_VALUE_LIST[group_key])
    if created:
      new_group.save()

    perm_list = []
    for (perm_key, perm_code_model) in settings.PLATFORM_USER_PERMISSION_LIST:
      perm_code, perm_app_model = perm_code_model.split(",")
      perm_name = settings.PLATFORM_USER_PERMISSION_VALUE_LIST[perm_key]

      if Permission.objects.filter(name=perm_name).exists() == False:

        # permission is added to a group, permission pertains to a content-type
        # can be a user or an initiative
        perm_app, perm_model = perm_app_model.split(".")
        perm = Permission(
          name=perm_name,
          codename=perm_code,
          content_type=ContentType.objects.get(app_label=perm_app, model=perm_model)
        )
        perm_list.append(perm)
        perm.save()

    if len(perm_list) > 0:
      new_group.permissions.add(perm_list)


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
