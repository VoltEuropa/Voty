# ==============================================================================
# Voty Initadmin Forms
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------
from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import ugettext as _

import account.forms

# ----------------------------- UploadFileForm ---------------------------------
class UploadFileForm(forms.Form):
  file = forms.FileField()

# ------------------------ LoginEmailOrUsernameForm ----------------------------
class LoginEmailOrUsernameForm(account.forms.LoginEmailForm):
  email = forms.CharField(label=_("Email or Username"), max_length=50) 

# ----------------------------- UserEditForm -----------------------------------
class UserEditForm(forms.ModelForm):
  
  class Meta:
    model = get_user_model()
    fields = ['first_name', 'last_name']
