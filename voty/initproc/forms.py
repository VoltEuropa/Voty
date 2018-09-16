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

from dal import autocomplete
from uuid import uuid4

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

# -------------------------- Simple Form Verifier ------------------------------
def simple_form_verifier(form_cls, template="fragments/simple_form.html", via_ajax=True,
                         submit_klasses="btn-outline-primary", submit_title=_("Send"),
                         submit_cancel_url=None):
  def wrap(fn):
    def view(request, *args, **kwargs):
      template_override = None
      if request.method == "POST":
        form = form_cls(request.POST)
        if form.is_valid():
          return fn(request, form, *args, **kwargs)
      else:
        form = form_cls(initial=request.GET)

      if request.GET.get("cancel", None) is not None:
        template_override="fragments/comment/comment_add.html"


      if submit_cancel_url:
        cancel_url = submit_cancel_url(request=request)
      else:
        cancel_url = None

      fragment = request.GET.get("fragment")
      rendered = render_to_string(
        template_override or template,
        context=dict(
          fragment=fragment,
          form=form,
          ajax=via_ajax,
          cancel_url=cancel_url,
          submit_klasses=submit_klasses,
          submit_title=submit_title
        ),
        request=request
      )
      if fragment:
        return {"inner-fragments": {fragment: rendered}}
      return rendered
    return view
  return wrap


# ============================= Classes ========================================
# ----------------------------- PolicyForm -------------------------------------
class PolicyForm(forms.ModelForm):

  class Meta:
    model = Policy
    fields = settings.PLATFORM_POLICY_BASE_CONFIG
    labels = settings.PLATFORM_POLICY_FIELD_LABELS
    help_texts = settings.PLATFORM_POLICY_FIELD_HELPER

  # add choices, sadly hardcoded field names here manually
  scope = forms.ChoiceField(
    choices=sorted(settings.CATEGORIES.SCOPE_CHOICES, key=lambda x: x[1]),
  )
  context = forms.ChoiceField(
    choices = sorted(settings.CATEGORIES.CONTEXT_CHOICES, key=lambda x: x[1]),
  )
  topic = forms.ChoiceField(
    choices = sorted(settings.CATEGORIES.TOPIC_CHOICES, key=lambda x: x[1]),
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

  # custom properties for fragments/simple_form.html
  title = _("Evaluate Policy Proposal")
  description = _("Please flag the policy if it:")

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

    # cannot give positive validation with a flag checked
    if cleaned_data['vote'] == 'y':
      for key in settings.PLATFORM_MODERATION_FIELD_LABELS:
        if cleaned_data[key]:
          self.add_error("vote", _("You cannot flag a Policy and approve it at the same time."))
          break

    # non-confirmations need to have a justification
    else:    
      if not cleaned_data['text']:
        self.add_error("text", _("Please briefly justify your validation to the initiator."))

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

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

# ----------------------------- InitiativeForm ---------------------------------
class InitiativeForm(forms.ModelForm):

    class Meta:
      model = Initiative
      fields = ['title', 'subtitle', 'summary', 'problem', 'forderung',
                'kosten', 'fin_vorschlag', 'arbeitsweise', 'init_argument',
                'einordnung', 'ebene', 'bereich']

      labels = {
          "title" : _("Headline"),
          "subtitle": _("Teaser"),
          "summary" : _("Summary"),
          "problem": _("Problem Assessment"),
          "forderung" : _("Proposal"),
          "kosten": _("Cost Estimation"),
          "fin_vorschlag": _("Finance Proposition"),
          "arbeitsweise": _("Methodology"),
          "init_argument": _("Initiators' Argument"),
          "einordnung": _("Context"),
          "ebene": _("Scope"),
          "bereich": _("Topic"),
      }
      help_texts = {
          "title" : _("The headline should state the proposal in a short and precise way."),
          "subtitle": _("Briefly describe the problem or situation, the Initiative should adress. Try limiting yourself to 1-2 sentences."),
          "summary" : _("Summarize the Initiative in 3-4 sentences."),
          "problem": _("State and assess the situation or problem, the Initiative should solve in 3-4 sentences."),
          "forderung": _("What are the concreted demands or proposals?"),
          "kosten": _("Will the Initiative cause costs? Try to give an estimation of the cost associated with the Initiative."),
          "fin_vorschlag": _("Briefly describe your ideas of how costs associated with the Initiative could be covered. It would be sufficient to write that the Initiative will be financed via tax income."),
          "arbeitsweise": _("Have you consulted experts? What information is your assessment based on? Is it possible to sources of information?"),
          "init_argument": _("Please state why this Initiative is important for you and why you are submitting it."),
      }




# --------------------------- NewArgumentForm ----------------------------------
class NewArgumentForm(forms.Form):
    TITLE = _("Add New Argument")
    type = forms.ChoiceField(choices=[('👍', '👍'), ('👎', '👎')], widget=forms.HiddenInput())
    title = forms.CharField(required=True,
                            label=_("Summary"),
                            max_length=140,
                            widget=forms.Textarea(attrs={'rows':3, 'placeholder':_("Arguments should be kept as clear as possible. Please ensure your argument is new and unique.")}))
    text = forms.CharField(required=True,
                           label=_("Complete Description"),
                           max_length=500,
                           widget=forms.Textarea(attrs={'rows':10, 'placeholder': _("If a similar Argument already exits, please add a comment to this Argument.")}))


# --------------------------- NewProposalForm ----------------------------------
class NewProposalForm(forms.Form):
    title = forms.CharField(required=True,
                            label=_("Summary"),
                            max_length=140,
                            widget=forms.Textarea(attrs={'rows':3, 'placeholder': _("Proposals should be kept as clear as possible. Please ensure your proposal is new and unique.")}))
    text = forms.CharField(required=True,
                           label=_("Detailed Overview"),
                           max_length=1000,
                           widget=forms.Textarea(attrs={'rows':10, 'placeholder': _("If a similar Proposal already exits, please add a comment to this Proposal.")}))


