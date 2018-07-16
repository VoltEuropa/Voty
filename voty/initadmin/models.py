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
# XXX should team lead be set here instead of in a separate group?
class UserConfig(models.Model):
  user = models.OneToOneField(User, related_name="config", on_delete=models.CASCADE)
  is_diverse_mod = models.BooleanField(default=False)
  is_female_mod = models.BooleanField(default=False)
  scope = models.CharField(choices=settings.CATEGORIES.SCOPE_CHOICES,max_length=100,default="eu")
  is_scope_confirmed = models.BooleanField(default=True)

  # without these new proper registrations will have no config accessible 
  @receiver(post_save, sender=User)
  def create_user_config(sender, instance, created, **kwargs):
    if created:
      UserConfig.objects.create(user=instance)
  
  @receiver(post_save, sender=User)
  def save_user_config(sender, instance, **kwargs):
    if getattr(instance, "config", None):
      instance.config.save()
    else:
      UserConfig.objects.create(user=instance)

