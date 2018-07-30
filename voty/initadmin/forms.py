# -*- coding: utf-8 -*-
# ==============================================================================
# Django initadmin forms
# ==============================================================================
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils.translation import ugettext as _
from django.conf import settings
from django.contrib.auth.forms import PasswordChangeForm

from account.models import SignupCode
from dal import autocomplete

from .models import UserConfig
import account.forms


# ------------------------ LoginEmailOrUsernameForm ----------------------------
class LoginEmailOrUsernameForm(account.forms.LoginEmailForm):
  email = forms.CharField(label=_("Email or Username"), max_length=50) 

  def get_success_url(self):
    url = super(LoginEmailOrUsernameForm, self).get_success_url()
    user = self.request.user
    if user.is_authenticated():
      language = user.config.preferred_language

      if language in [x[1] for x in settings.ACCOUNT_LANGUAGES]:
        activate(language)
        if hasattr(self.request, 'session'):
          self.request.session[LANGUAGE_SESSION_KEY] = language

    return url
        

# ============================ User Settings ===================================
# ---------------------------- Edit Profile ------------------------------------
class UserEditForm(forms.ModelForm):

  class Meta:
    model = get_user_model()
    fields = ["first_name", "last_name", "username", "email"]

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
      self.fields[field].widget.attrs.update({
        'class': 'form-control'
      })

  email = forms.CharField(
    widget=forms.TextInput(attrs={"readonly": True}),
    disabled=True
  )
  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="edit_profile"
  )

# ---------------------------- Edit Password -----------------------------------
class CustomPasswordChangeForm(PasswordChangeForm):

  class Meta:
    fields = ["old_password", "new_password1", "new_password2"]

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
      self.fields[field].widget.attrs.update({
        'class': 'form-control',
      })
    self.fields['old_password'].widget.attrs.pop("autofocus", None)

  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="edit_password"
  )

# ------------------------------ Edit Scope ------------------------------------
class UserLocaliseForm(forms.ModelForm):

  class Meta:
    model = UserConfig
    fields = ["scope", "is_scope_confirmed"]

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
      self.fields[field].widget.attrs.update({
        'class': 'form-control'
      })

  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="edit_scope"
  )

# ----------------------------- Edit Language ----------------------------------
class UserLanguageForm(forms.ModelForm):

  class Meta:
    model = UserConfig
    fields = ["language_preference"]

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
      self.fields[field].widget.attrs.update({
        'class': 'form-control'
      })

  language_preference = forms.ChoiceField(
    required=True,
    label=_("Languages"),
    choices=sorted(settings.ACCOUNT_LANGUAGES, key=lambda x: x[1]),
    help_text=_("Please select your preferred language.")
  )
  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="edit_language"
  )

# -----------------------------Delete Account ----------------------------------
# XXX Almost to UserDeleteForm
class UserDeleteAccount(forms.ModelForm):

  class Meta:
    model = get_user_model()
    fields = ["username"]
    labels = {
      "username": _("Username"),
    }
    help_texts = {
      "username": _("Please rewrite your username to confirm you really want to delete your account."),
    }

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
      self.fields[field].widget.attrs.update({
        'class': 'form-control'
      })

  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="delete_account"
  )


# ============================= Invite Users ===================================
# ------------------------------ File Uploads ----------------------------------
class UploadFileForm(forms.Form):
  file = forms.FileField()
  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="invite_batch"
  )

# ------------------------------ Invite Users ----------------------------------
class UserInviteForm(forms.ModelForm):

  class Meta:
    model = get_user_model()
    fields = ["first_name", "email"]

  first_name = forms.CharField(required=True)
  email = forms.CharField(required=True)
  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="invite_user"
  )

# --------------------------- Delete Signup Codes ------------------------------
class DeleteSignupCodeForm(forms.ModelForm):

  class Meta:
    model = SignupCode
    fields = ["id"]

  # XXX docs say this is bad if >100 entries to query
  id = forms.ModelChoiceField(
    label=_("Search by Email address"),
    queryset=SignupCode.objects.all(),
    required=False,
    widget=autocomplete.ModelSelect2(
      url='signupcode_autocomplete',
     attrs={
        "data-placeholder": _("Type to search"),
        "data-html": True
      }
    )
  )
  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="delete_signup"
  )

# ============================ Moderate User ===================================
# -------------------------- Edit Profile/Email --------------------------------
class UserModerateForm(forms.ModelForm):

  class Meta:
    model = get_user_model()
    fields = ["username", "first_name", "last_name", "email"]

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
      self.fields[field].widget.attrs.update({
        'class': 'form-control'
      })

  # override fields
  first_name = forms.CharField(
    widget=forms.TextInput(attrs={"readonly": True}),
    disabled=True
  )
  last_name = forms.CharField(
    widget=forms.TextInput(attrs={"readonly": True}),
    disabled=True
  )
  username = forms.CharField(
    widget=forms.TextInput(attrs={"readonly": True}),
    disabled=True
  )
  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="reset_email"
  )

# ------------------------ Add/Remove Group Membership -------------------------
class UserGiveGroupPrivilegeForm(forms.ModelForm):

  class Meta:
    model = get_user_model()
    fields = ["groups"]

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
      self.fields[field].widget.attrs.update({
        'class': 'form-control'
      })

  groups = forms.MultipleChoiceField(
    #widget=forms.CheckboxSelectMultiple,choices=[(x.id, x.name) for x in Group.objects.all()],
    widget=forms.CheckboxSelectMultiple,
    required=False,
    label=_("Groups"),
    help_text=_("Please select the group(s) this user should belong to. This will give the user permissions associated with the respective group.")
  )
  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="give_group_privileges"
  )

# ------------------------ Add/Remove Diversity Flags --------------------------
class UserAddDiversityFlagsForm(forms.ModelForm):

  class Meta:
    model = UserConfig
    fields = ["is_female_mod", "is_diverse_mod"]

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
      self.fields[field].widget.attrs.update({
        'class': 'form-control'
      })

  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="add_diversify_flags"
  )


# ----------------------------- Validate User Scope ----------------------------
class UserValidateLocalisationForm(forms.ModelForm):

  class Meta:
    model = get_user_model()
    fields = ["groups"]

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
      self.fields[field].widget.attrs.update({
        'class': 'form-control'
      })

  scope = forms.ChoiceField(
    required=True,
    label=_("Scope"),
    choices=sorted(settings.CATEGORIES.SCOPE_CHOICES, key=lambda x: x[1]),
    help_text=_("User participation scope.")
  )
  is_scope_confirmed = forms.ChoiceField(
    required=True,
    label=_("Set Scope to:"),
    choices=[("1", _("Validated")), ("0", _("Not Validated"))],
    help_text=_("Validate or invalidate the requested/current scope")
  )
  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="validate_scope"
  )

# --------------------------- Activate/Deactivate User -------------------------
class UserActivateForm(forms.ModelForm):

  class Meta:
    model = get_user_model()
    fields = ["last_login", "is_active"]

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
      self.fields[field].widget.attrs.update({
        'class': 'form-control'
      })

  last_login = forms.CharField(
    widget=forms.TextInput(attrs={"readonly": True})
  )
  status = forms.ChoiceField(
    required=True,
    label=_("Set Account to:"),
    choices=[("1", _("Active")), ("0", _("Inactive"))],
    help_text=_("While inactive users can no longer login into their account. They remain in the database until deleted or reactivated.")
  )
  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="activate_account"
  )

# ------------------------------- Delete User ----------------------------------
class UserDeleteForm(forms.ModelForm):

  class Meta:
    model = get_user_model()
    fields = ["username"]
    labels = {
      "username": _("Username"),
    }
    help_texts = {
      "username": _("Please rewrite the username to confirm this is the user you want to delete."),
    }

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in iter(self.fields):
      self.fields[field].widget.attrs.update({
        'class': 'form-control'
      })

  action = forms.CharField(
    max_length=24,
    widget=forms.HiddenInput(),
    initial="delete_account"
  )

# =============================== Listboxes ====================================                    
# --------------------------- ListboxSearchForm --------------------------------
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
