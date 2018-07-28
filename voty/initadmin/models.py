# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initadmin models
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------
from django.contrib.auth.models import User
from datetime import datetime, timedelta, date
from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

import pytz

# ----------------------------- InviteBatch ------------------------------------
class InviteBatch(models.Model):
  created_at = models.DateTimeField(auto_now_add=True, null=False, blank=False)
  total_found = models.IntegerField(default=0)
  new_added = models.IntegerField(default=0)
  payload = models.TextField()

# ----------------------------- UserConfig -------------------------------------
class UserConfig(models.Model): 
  user = models.OneToOneField(User, related_name="config", on_delete=models.CASCADE)
  scope = models.CharField(choices=settings.CATEGORIES.SCOPE_CHOICES,max_length=100,default="eu")

  is_diverse_mod = models.BooleanField(default=False)
  is_female_mod = models.BooleanField(default=False)
  is_scope_confirmed = models.BooleanField(default=True)

  # XXX eventually switch to proper language codes = en-en instead of en
  language_preference = models.CharField(choices=settings.ACCOUNT_LANGUAGES,max_length=100,default=settings.LANGUAGE_CODE.split("-")[0])

  # catch-all field to show all flags set on a user
  is_flagged = models.CharField(blank=True,max_length=200,default="")

  # supposedly without post_save new registrations will have no config. but
  # both creating users in admin interface and via signup code works and
  # creates the user plus config. So comment out for now, because this will
  # call post and "put" a second time and throw unique-id errors.

  # dispatch https://code.djangoproject.com/wiki/Signals#Helppost_saveseemstobeemittedtwiceforeachsave
  @receiver(post_save, sender=User, dispatch_uid="some_string_create_user_config")
  def create_user_config(sender, instance, created, **kwargs):
    if created:
      UserConfig.objects.create(user=instance)

  #@receiver(post_save, sender=User, dispatch_uid="some_string_update_user_config")
  #def save_user_config(sender, instance, created, **kwargs):
  #  if getattr(instance, "config", None):
  #    UserConfig.objects.create(user=instance)
  #  else:
  #    instance.config.save()

