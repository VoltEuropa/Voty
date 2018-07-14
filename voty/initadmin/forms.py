# ==============================================================================
# Voty Initadmin Forms
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
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
    fields = ["first_name", "last_name"]

# --------------------------- UserModerateFrom ---------------------------------
class UserModerateForm(forms.ModelForm):

  class Meta:
    model = get_user_model()
    fields = ["groups", "username", "first_name", "last_name", "email", "is_active", "last_login"]
    # doesn't work - readonly_fields = ("username",),

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
      self.fields[field].widget.attrs.update({
        'class': 'form-control'
      })

  # override fields
  first_name = forms.CharField(
    widget=forms.TextInput(attrs={"readonly": True})
  )
  last_name = forms.CharField(
    widget=forms.TextInput(attrs={"readonly": True})
  )
  username = forms.CharField(
    widget=forms.TextInput(attrs={"readonly": True})
  )
  last_login = forms.CharField(
    widget=forms.TextInput(attrs={"readonly": True})
  )

  scope = forms.ChoiceField(
    required=True,
    label=_("Scope"),
    choices=settings.CATEGORIES.SCOPE_CHOICES,
    help_text=_("User participation scope.")
  )
  is_scope_confirmed = forms.ChoiceField(
    required=True,
    label=_("Set Scope to:"),
    choices=[("1", _("Validated")), ("0", _("Not Validated"))],
    help_text=_("Validate or invalidate the requested/current scope")
  )
  status = forms.ChoiceField(
    required=True,
    label=_("Set Account to:"),
    choices=[("1", _("Active")), ("0", _("Inactive"))],
    help_text=_("Inactive Users can no longer login into their account")
  )
  groups = forms.MultipleChoiceField(
    widget=forms.CheckboxSelectMultiple,choices=[(x.id, x.name) for x in Group.objects.all()],
    required=False,
    label=_("Groups"),
    help_text=_("Please select the group(s) this user should belong to. This will give the user permissions associated with the respective group.")
  )
                       
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

  search = forms.CharField(
    widget=forms.TextInput(attrs={'placeholder': _('Search...')}),
    required=False,
    label=_("Search"),
    max_length=50,
    min_length=3
  )
  records = forms.ChoiceField(
    required=False,
    label=_("Records"),
    choices=settings.LISTBOX_OPTION_DICT.NUMBER_OF_RECORDS_OPTION_LIST
  )
