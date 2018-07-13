# ==============================================================================
# Voty Initadmin Forms
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------
from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import ugettext as _
from django.conf import settings

from .models import UserConfig
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

# -------------------------- ListboxSearchForm ---------------------------------
class ListboxSearchForm(forms.ModelForm):
  
  class Meta:
    model = UserConfig
    fields = ["scope"]

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
        self.fields[field].widget.attrs.update({
            'class': 'form-control'
    })

  search = forms.CharField(widget=forms.TextInput(attrs={'placeholder': _('Search...')}),required=False,label=_("Search"),max_length=50,min_length=3)
  records = forms.ChoiceField(required=False,label=_("Records"),choices=settings.LISTBOX_OPTION_DICT.NUMBER_OF_RECORDS_OPTION_LIST)



