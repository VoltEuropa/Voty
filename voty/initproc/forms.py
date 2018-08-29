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

# ============================= Classes ========================================
def simple_form_verifier(form_cls, template="fragments/simple_form.html", via_ajax=True,
                         submit_klasses="btn-outline-primary", submit_title=_("Send")):
    def wrap(fn):
        def view(request, *args, **kwargs):
            if request.method == "POST":
                form = form_cls(request.POST)
                if form.is_valid():
                    return fn(request, form, *args, **kwargs)
            else:
                form = form_cls(initial=request.GET)

            fragment = request.GET.get('fragment')
            rendered = render_to_string(template,
                        context=dict(fragment=fragment, form=form, ajax=via_ajax,
                                     submit_klasses=submit_klasses,
                                     submit_title=submit_title),
                        request=request)
            if fragment:
                return {'inner-fragments': {fragment: rendered}}
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
        label=_("Invite"),
        queryset=get_user_model().objects,
        required=False,
        widget=autocomplete.ModelSelect2Multiple(
                    url='user_autocomplete',
                    attrs={"data-placeholder": _("Type to search"),
                           'data-html': "True"}))

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


# --------------------------- NewCommentForm -----------------------------------
class NewCommentForm(forms.ModelForm):
    text = forms.CharField(required=True, label=_("Your comment"),
                           help_text=_("Paragraphs and urls will be formatted"),
                           max_length=500, widget=forms.Textarea(attrs={'rows':10, 'placeholder': _("Please refer to the above Argument in your comment.")}))

    class Meta:
        model = Comment
        fields = ['text']

# -------------------------- NewModerationForm ---------------------------------
QESTIONS_COUNT = 11
class NewModerationForm(forms.ModelForm):


    TITLE = _("Moderation")
    TEXT = _("The Initiative ... (please remove non-fitting characteristics")

    q0 = forms.BooleanField(required=False, initial=True, label=_("Contradicts in some point with human rights or human dignity"))
    q1 = forms.BooleanField(required=False, initial=True, label=_("Contains pejorative terms against certain groups (eg Immigrants"))
    q2 = forms.BooleanField(required=False, initial=True, label=_("Is excluding/rasict/homophobe/discriminatory/transphobe/sexist"))
    q3 = forms.BooleanField(required=False, initial=True, label=_("Is nationalistic"))
    q4 = forms.BooleanField(required=False, initial=True, label=_("Is un-democratic?"))
    q5 = forms.BooleanField(required=False, initial=True, label=_("Leads to less transparency"))
    q6 = forms.BooleanField(required=False, initial=True, label=_("Leads to more patronizing or exclusion of persons in participating"))
    q7 = forms.BooleanField(required=False, initial=True, label=_("Is putting a burden on future generations"))
    q8 = forms.BooleanField(required=False, initial=True, label=_("Endangers the climate and our planet"))
    q9 = forms.BooleanField(required=False, initial=True, label=_("Leads to a widening of the prospertiy divide (rich get richer, poor get poorer"))
    q10 = forms.BooleanField(required=False, initial=True, label=_("Puts groups of disadvantaged persons at even more disadvantages."))
    text = forms.CharField(required=False, label=_("Comment/Hint/Remark"), widget=forms.Textarea)
    vote = forms.ChoiceField(required=True, label=_("Your Assessment"),
            choices=[('y', 'yay'),('n', 'nope')],
            widget=forms.RadioSelect())

    def clean(self):
        cleanded_data = super().clean()
        if cleanded_data['vote'] == 'y':
            for i in range(QESTIONS_COUNT):
                if cleanded_data['q{}'.format(i) ]:
                    self.add_error("vote", _("You voted postively, although you marked at least one of the above issues."))
                    break
        else:
            if not cleanded_data['text']:
                self.add_error("text", _("Can you justifiy your decision?"))

    class Meta:
        model = Moderation
        fields = ['q{}'.format(i) for i in range(QESTIONS_COUNT)] + ['text', 'vote']
