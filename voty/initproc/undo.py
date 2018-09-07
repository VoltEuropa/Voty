# -*- coding: utf-8 -*-
# ==============================================================================
# voty initproc undo - token generator to revert (accidental) actions
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils import six
from django.utils.crypto import constant_time_compare, salted_hmac
from django.conf import settings
from django.utils.encoding import force_text
from django.utils.http import urlsafe_base64_decode
from django.utils.translation import ugettext as _

from datetime import datetime, timedelta
import base64

# ------------------------ Undo Token Generator --------------------------------
class UndoUrlTokenGenerator(PasswordResetTokenGenerator):

  def _make_hash_value(self, key, timestamp):
    return (six.text_type(key) + six.text_type(timestamp))

  def _make_token_with_timestamp(self, key, state, timestamp):
    ts_b64 = base64.b64encode(bytes((six.text_type(timestamp) + "-" + state), 'utf-8')).decode("UTF-8")

    hash = salted_hmac(
      settings.SECRET_KEY,
      self._make_hash_value(key, timestamp),
    ).hexdigest()[::2]

    return "%s/%s" % (ts_b64, hash)

  def create_token(self, user, policy):
    return self._make_token_with_timestamp(user.pk, policy.state, datetime.now())

  def validate_token(self, user, token):
    state = error = None
    try:
      ts_b64, hash = token.split("/")
    except ValueError:
      error = _("Undo token corrupted.")

    try:
      ts, state = base64.b64decode(ts_b64).decode().rsplit("-", 1)
    except ValueError:
      error = _("Undo token corrupted.")

    # Check that the timestamp/uid has not been tampered with
    if not constant_time_compare(self._make_token_with_timestamp(user.pk, state, ts), token):
      error = _("Undo token corrupted.")

    # Check the timestamp is within limit
    if datetime.now() - timedelta(seconds=int(settings.PLATFORM_UNDO_TIMEOUT)) > datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f"):
      error = _("Undo token expired.")

    return state, error

