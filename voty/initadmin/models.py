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
