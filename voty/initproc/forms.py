# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initproc forms
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

from django import forms
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth import get_user_model
from django.conf import settings
from .models import Tag

from dal import autocomplete
from uuid import uuid4
import tagulous.forms
import tagulous.models

from .models import Pro, Contra, Like, Comment, Proposal, Moderation, Initiative, Policy

# =============================== HELPERS ======================================
# ------------------------ Build Class field dict .-----------------------------
# XXX duplicate to models.py, only switched forms for models. Create mixin!
def _create_class_field_dict(field_dict):
  response = {}

  # XXX refactor...
  for field_key, field_value in field_dict.items():
    field_type, field_param_list = field_value.split("|")
    config_list = []

    for config_entry in field_param_list.split(","):
      key, value = config_entry.split("=")
      value_type, value_value = value.split(":")
      if value_type == "int":
        value_value = int(value_value)
      elif value_type == "bool":
        if value_value == "True":
          value_value = True
        else:
          value_value = False
      
      config_list.append([key, value_value])
    response[field_key] = getattr(forms, field_type)(**dict(config_list))

  return response

# ============================= Classes ========================================
# ----------------------------- PolicyForm -------------------------------------
class PolicyForm(forms.ModelForm):

  class Meta:
    model = Policy
    fields = settings.PLATFORM_POLICY_BASE_CONFIG
    labels = settings.PLATFORM_POLICY_FIELD_LABELS
    help_texts = settings.PLATFORM_POLICY_FIELD_HELPER

  # add choices, sadly requires hardcoded field names
  scope = forms.ChoiceField(
    choices=sorted(settings.CATEGORIES.SCOPE_CHOICES, key=lambda x: x[1]),
  )
  context = forms.ChoiceField(
    choices = sorted(settings.CATEGORIES.CONTEXT_CHOICES, key=lambda x: x[1]),
  )
  topic = forms.ChoiceField(
    choices = sorted(settings.CATEGORIES.TOPIC_CHOICES, key=lambda x: x[1]),
  )
  tags = tagulous.forms.TagField(
    tag_options=Policy.tags.tag_options + tagulous.models.TagOptions(
      autocomplete_view='policy_tags_autocomplete',
    ),
  )

# --------------------------- InviteUsersForm ----------------------------------
class InviteUsersForm(forms.Form):

  user = forms.ModelMultipleChoiceField(
    label=_("Invite Co-Initiators"),
    queryset=get_user_model().objects,
    required=False,
    widget=autocomplete.ModelSelect2Multiple(
      url='user_autocomplete',
      attrs={"data-placeholder": _("Type to search"), 'data-html': "True"}
    )
  )

# -------------------------- NewModerationForm ---------------------------------
class NewModerationForm(forms.ModelForm):

  class Meta:
    model = Moderation
    fields = ["text", "vote"]

  # custom properties for fragments/simple_form.html, used to be TITLE/TEXT to
  # not conflict with title/text
  form_title = _("Evaluate Policy Proposal")
  form_description = _("Please set a blocker on the policy if it:")

  text = forms.CharField(
    widget=forms.Textarea,
    required=False,
    label=_("Comment/Hints/Remarks"),
  )
  vote = forms.ChoiceField(
    widget=forms.RadioSelect(),
    required=True,
    label=_("Final Assessment:"),
    choices=sorted(settings.PLATFORM_MODERATION_CHOICE_LIST, key=lambda x: x[1]),
  )

  def clean(self):
    cleaned_data = super().clean()
    blocker = None

    # cannot give positive validation with a flag checked
    if cleaned_data['vote'] == 'y':
      for key in settings.PLATFORM_MODERATION_FIELD_LABELS:
        if cleaned_data[key]:
          self.add_error("vote", _("You cannot set a blocker on a Policy and approve it at the same time."))
          break

    if cleaned_data["vote"] == 'n':
      for key in settings.PLATFORM_MODERATION_FIELD_LABELS :
        if cleaned_data[key]:
          blocker = True
      if not blocker:
        self.add_error("vote", _("You have to set at least one flag when disapproving a Policy."))

    # non-confirmations need to have a justification
    else: 
      if not cleaned_data['text']:
        self.add_error("text", _("Please briefly justify your validation to the initiator."))

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

    # so much time spent here to add the challenged flag to the link calling 
    # the form so we can check it on form-init and remove the request option
    # from the vote choices as in a challenge, there is only a final verdict
    
    if kwargs and "challenged" in kwargs["initial"]:
      self.fields["vote"].choices = self.fields["vote"].choices[:-1]

    # Note: we're adding a lot of checks dynamically here which need to be 
    # unchecked for the actual moderation (which doesn't store them) to be saved
    field_dict = _create_class_field_dict(settings.PLATFORM_MODERATION_BASE_CONFIG)
    field_order = []
    for key in field_dict:
      field_dict[key].label = settings.PLATFORM_MODERATION_FIELD_LABELS[key]
      self.fields[key] = field_dict[key]
      field_order.append(key)
    self.order_fields(field_order)

# --------------------------- NewCommentForm -----------------------------------
class NewCommentForm(forms.ModelForm):

  class Meta:
    model = Comment
    fields = ['text']
    
  text = forms.CharField(
    required=True,
    label=_("Your comment"),
    help_text=_("Paragraphs and urls will be formatted"),
    max_length=500,
    widget=forms.Textarea(attrs={'rows':10, 'placeholder': _("Please refer to the above Argument in your comment.")})
  )

# --------------------------- NewProposalForm ----------------------------------
class NewProposalForm(forms.Form):

  form_title = _("Add a Proposal")
  form_description = _("Use proposals in case of issues, corrections or if you think the Policy should be modified or extended.")

  title = forms.CharField(
    required=True,
    label=_("Summary"),
    max_length=140,
    widget=forms.Textarea(
      attrs={
        "rows":3,
        "placeholder": _("Please be precise and verify your proposal is new and unique.")
      }
    )
  )

  text = forms.CharField(
    required=True,
    label=_("Detailed Overview"),
    max_length=1000,
    widget=forms.Textarea(
      attrs={
        "rows":10,
        "placeholder": _("If a similar Proposal already exits, please add a comment to this Proposal.")
      }
    )
  )

# --------------------------- NewArgumentForm ----------------------------------
class NewArgumentForm(forms.Form):

  form_title = _("Add New Argument")
  form_description = _("Use arguments for questions or to leave feedback and comments.")

  type = forms.ChoiceField(
    choices=[("thumbs_up", "thumbs_up"), ("thumbs_down", "thumbs_down")],
    widget=forms.HiddenInput()
  )

  title = forms.CharField(
    required = True,
    label = _("Summary"),
    max_length = 140,
    widget = forms.Textarea(
      attrs = {
        "rows":3,
        "placeholder": _("Arguments should be kept as clear as possible. Please ensure your argument is new and unique.")
      }
    )
  )

  text = forms.CharField(
    required = True,
    label = _("Complete Description"),
    max_length = 500,
    widget = forms.Textarea(
      attrs={
        "rows":10,
        "placeholder": _("If a similar Argument already exits, please add a comment to this Argument.")
      }
    )
  )
