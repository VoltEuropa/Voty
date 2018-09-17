# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initproc views/actions
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_POST
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.decorators import available_attrs
from django.utils.safestring import mark_safe
from django.contrib.postgres.search import SearchVector
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.conf import settings
from django.apps import apps
from django.db.models import Q
from django.db import connection
from dal import autocomplete
from django import forms

from datetime import datetime, timedelta

from rest_framework.renderers import JSONRenderer
from django_ajax.shortcuts import render_to_json
from django_ajax.decorators import ajax
from pinax.notifications.models import send as notify
from notifications.models import Notification
from reversion_compare.helpers import html_diff
from reversion.models import Version
import reversion

from functools import wraps
import json

from .globals import STATES, VOTED, INITIATORS_COUNT, COMPARING_FIELDS
from .models import (Policy, Initiative, Pro, Contra, Proposal, Comment, Vote, Moderation, Quorum, Supporter, Like)
from .forms import (PolicyForm, InitiativeForm, NewArgumentForm, NewCommentForm,
                    NewProposalForm, NewModerationForm, InviteUsersForm)
from .undo import UndoUrlTokenGenerator
from .serializers import SimpleInitiativeSerializer
from django.contrib.auth.models import Permission
from django.utils.translation import ugettext as _

DEFAULT_FILTERS = [
    STATES.PREPARE,
    STATES.INCOMING,
    STATES.SEEKING_SUPPORT,
    STATES.DISCUSSION,
    STATES.VOTING]

def param_as_bool(param):
    try:
        return bool(int(param))
    except ValueError:
        return param.lower() in ['true', 'y', 'yes', '✔', '✔', 'j', 'ja' 'yay', 'yop', 'yope']


def non_ajax_redir(*redir_args, **redir_kwargs):
    def decorator(func):
        @wraps(func, assigned=available_attrs(func))
        def inner(request, *args, **kwargs):
            if not request.is_ajax():
                # we redirect you 
                return redirect(*redir_args, **redir_kwargs)
            return func(request, *args, **kwargs)

        return inner
    return decorator

def get_voting_fragments(vote, initiative, request):
    context = dict(vote=vote, initiative=initiative, user_count=initiative.eligible_voter_count)
    return {'fragments': {
        '#voting': render_to_string("fragments/voting.html",
                                    context=context,
                                    request=request),
        '#jump-to-vote': render_to_string("fragments/jump_to_vote.html",
                                    context=context)
        }}

# ============================= HELPERS ========================================
# -------------------------- Simple Form Verifier ------------------------------
def simple_form_verifier(form_cls, template="fragments/simple_form.html", via_ajax=True,
                         submit_klasses="btn-outline-primary", submit_title=_("Send"),
                         cancel=None, cancel_template=None):
  def wrap(fn):
    def view(request, *args, **kwargs):
      template_override = None

      if request.method == "POST":
        form = form_cls(request.POST)
        if form.is_valid():
          return fn(request, form, *args, **kwargs)
      else:
        form = form_cls(initial=request.GET)

      # calling the method in views.py to build the url
      if cancel:
        cancel_url = request.get_full_path() + "&cancel=True"
      else:
        cancel_url = None

      fragment = request.GET.get("fragment")

      # to cancel we need the parent object... actually the whole things is a
      # few and not a form...
      if request.GET.get("cancel", None) is not None:
      
        model_class = apps.get_model('initproc', kwargs["target_type"])
        target_object = get_object_or_404(model_class, pk=kwargs["target_id"])

        rendered = render_to_string(
          cancel_template,
          context=dict(
            fragment=fragment,
            m=target_object
          ),
          request=request
        )
      else:
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

# --------------------- State Permission decorator -----------------------------
# moved here from guard.py
def policy_state_access(states=None):
  def wrap(fn):
    def view(request, policy_id, *args, **kwargs):
      policy = get_object_or_404(Policy, pk=policy_id)

      if states:
        assert policy.state in states, "{} Not in expected state: {}".format(policy.state, states)

      # NOTE: this adds the policy on the request, that's why the decorator has
      # to be called on all views which need the current policy.
      request.policy = policy
      return fn(request, policy, *args, **kwargs)
    return view
  return wrap

# --------------------------- personalise arguments ----------------------------
def _personalize_argument(arg, user_id):
  arg.has_liked = arg.likes.filter(user=user_id).exists()
  arg.has_commented = arg.comments.filter(user__id=user_id).exists()

#def _set_cancel_url(request=None, *args, **kwargs):
#  return request.get_full_path() + "&cancel=True"

#
# ____    ____  __   ___________    __    ____   _______.
# \   \  /   / |  | |   ____\   \  /  \  /   /  /       |
#  \   \/   /  |  | |  |__   \   \/    \/   /  |   (----`
#   \      /   |  | |   __|   \            /    \   \    
#    \    /    |  | |  |____   \    /\    / .----)   |   
#     \__/     |__| |_______|   \__/  \__/  |_______/    
#
#                                                       

# ----------------------------- Policy Item ------------------------------------
@policy_state_access()
def policy_item(request, policy, *args, **kwargs):

  if not request.guard.policy_view(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("home")

  payload = dict(
    policy=policy,
    user_count=policy.eligible_voter_count,
    policy_proposals=[x for x in policy.policy_proposals.prefetch_related("likes").all()],
    policy_arguments=[x for x in policy.policy_pros.prefetch_related('likes').all()] + \
      [x for x in policy.policy_contras.prefetch_related("likes").all()]
  )

  payload["policy_arguments"].sort(key=lambda x: (-x.policy_likes.count(), x.created_at))
  payload["policy_proposals"].sort(key=lambda x: (-x.policy_likes.count(), x.created_at))
  payload["is_likeable"] = request.guard.is_likeable (policy)

  # personalise if authenticated user interacted with policy
  if request.user.is_authenticated:
    user_id = request.user.id
    payload.update({"has_supported": policy.supporting_policy.filter(user=user_id).count()})
    policy_votes = policy.policy_votes.filter(user=user_id)
    if (policy_votes.exists()):
      payload['policy_vote'] = policy_votes.first()
    for arg in payload['policy_arguments'] + payload['policy_proposals']:
      _personalize_argument(arg, user_id)

  return render(request, 'initproc/policy_item.html', context=payload)

# ----------------------------- Policy Edit ------------------------------------
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_EDIT_STATE_LIST)
def policy_edit(request, policy, *args, **kwargs):

  if not request.guard.policy_view(policy) or not request.guard.policy_edit(policy):
    messages.warning(request, _("Permission denied."))
    return policy_item(request, policy.id, *args, **kwargs)

  form = PolicyForm(request.POST or None, instance=policy)
  if request.method == 'POST':
    user = request.user
    if form.is_valid():
      with reversion.create_revision():
        policy.save()
        reversion.set_user(user)

      # ask initial supporters to repledge? draft, only author can edit, 
      # will not be notified. if staged, initiators will be notified to repledge
      supporters = policy.supporting_policy.filter(initiator=True).exclude(user_id=user.id)
      supporters.update(ack=False)
      notify(
        [supporter.user for _, supporter in enumerate(supporters)],
        settings.NOTIFICATIONS.PUBLIC.POLICY_EDITED, {
        "description": "".join([_("Policy edited:"), " ", policy.title, ". ", _("Please reconfirm your support.")])
        }, sender=user
      )
      messages.success(request, _("Policy updated."))
      return redirect("/policy/{}".format(policy.id))
    else:
      messages.warning(request, _("Please correct the following problems:"))

  return render(request, "initproc/policy_edit.html", context=dict(form=form, policy=policy))

# ----------------------------- Policy New -------------------------------------
# careful, not going through the state filter, so params are different
@login_required
def policy_new(request, *args, **kwargs):

  form = PolicyForm(request.POST or None)
  if request.method == 'POST':
    if form.is_valid():
      user = request.user
      policy_object = form.save(commit=False)
      with reversion.create_revision():
        policy_object.state = settings.PLATFORM_POLICY_STATE_DEFAULT
        policy_object.save()

        # Store some meta-information.
        reversion.set_user(user)

      Supporter(policy=policy_object, user=user, first=True, initiator=True, ack=True, public=True).save()
      messages.success(request, _("Created new Policy draft."))
      return redirect('/policy/{}-{}'.format(policy_object.id, policy_object.slug))
    else:
      messages.warning(request, _("Please fill out all required fields."))

  return render(request, 'initproc/policy_edit.html', context=dict(form=form))

# ------------------------- Policy Validation Show -----------------------------
# toggle review feedback
@ajax
@login_required
@policy_state_access()
def policy_feedback(request, policy, *args, **kwargs):

  moderation = get_object_or_404(Moderation, pk=kwargs["target_id"])

  # toggle the comment thread
  fake_context = dict(
    m=moderation,
    policy=policy,
    has_commented=False,
    is_likeable=True,
    full=1 if request.GET.get('toggle', None) is None else 0,
    comments=moderation.comments.order_by('created_at').all()
  )

  if request.user:

    # XXX what if >1 comments? this should be called on comments instead
    # fake_context["has_liked"] = moderation.likes.filter(user=request.user).exists()
    for comment in fake_context["comments"]:
      if request.user.id != comment.user.id:
        comment.has_liked = comment.likes.filter(user=request.user).exists()
      else:
        comment.can_modify = request.guard.is_editable

    # don't allow two-in-a-row
    if not request.guard.target_comment(moderation):
      fake_context["has_commented"] = True

  return {
    "fragments": {
      "#policy-{moderation.type}-{moderation.id}".format(moderation=moderation): render_to_string(
        "fragments/moderation/moderation_item.html",
        context=fake_context,
        request=request,
      )
    }
  }



def about(request):
    return render(request, 'static/about.html', context=dict(
            quorums=Quorum.objects.order_by("-created_at")))

def account_language(request):
    return render(request, "account/language.html")

def crawler(request, filename):
    return render(request, filename, {}, content_type="text/plain")

def index(request):
    filters = [f for f in request.GET.getlist("f")]
    if filters:
        request.session['init_filters'] = filters
    else:
        filters = request.session.get('init_filters', DEFAULT_FILTERS)

    inits = request.guard.make_intiatives_query(filters).prefetch_related("supporting_initiative")

    bereiche = [f for f in request.GET.getlist('b')]
    if bereiche:
        inits = inits.filter(bereich__in=bereiche)

    ids = [i for i in request.GET.getlist('id')]

    if ids:
        inits = inits.filter(id__in=ids)

    elif request.GET.get('s', None):
        searchstr = request.GET.get('s')

        if len(searchstr) >= settings.MIN_SEARCH_LENGTH:
            if connection.vendor == 'postgresql':
                inits = inits.annotate(search=SearchVector('title', 'subtitle','summary',
                        'problem', 'forderung', 'kosten', 'fin_vorschlag', 'arbeitsweise', 'init_argument')
                    ).filter(search=searchstr)
            else:
                inits = inits.filter(Q(title__icontains=searchstr) | Q(subtitle__icontains=searchstr))


    inits = sorted(inits, key=lambda x: x.sort_index or timedelta(days=1000))

    # now we filter for urgency


    if request.is_ajax():
        return render_to_json(
            {'fragments': {
                "#init-card-{}".format(init.id) : render_to_string("fragments/initiative/card.html",
                                                               context=dict(initiative=init),
                                                               request=request)
                    for init in inits },
             'inner-fragments': {
                '#init-list': render_to_string("fragments/initiative/list.html",
                                               context=dict(initiatives=inits),
                                               request=request)
             },
             # FIXME: ugly work-a-round as long as we use django-ajax
             #        for rendering - we have to pass it as a dict
             #        or it chokes on rendering :(
             'initiatives': json.loads(JSONRenderer().render(
                                SimpleInitiativeSerializer(inits, many=True).data,
                            ))
        }
)



    count_inbox = request.guard.make_intiatives_query(['i']).count()

    return render(request, 'initproc/index.html',context=dict(initiatives=inits,
                    inbox_count=count_inbox, filters=filters))



class UserAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated():
            return get_user_model().objects.none()

        qs = get_user_model().objects.filter(is_active=True).all()

        if self.q:
            qs = qs.filter(Q(first_name__icontains=self.q) | Q(last_name__icontains=self.q) | Q(username__icontains=self.q))

        return qs

    def get_result_label(self, item):
        return render_to_string('fragments/autocomplete/user_item.html',
                                context=dict(user=item))

@login_required
def new(request):
    form = InitiativeForm()
    if request.method == 'POST':
        form = InitiativeForm(request.POST)
        if form.is_valid():
            ini = form.save(commit=False)
            with reversion.create_revision():
                ini.state = STATES.PREPARE
                ini.save()

                # Store some meta-information.
                reversion.set_user(request.user)
                if request.POST.get('commit_message', None):
                    reversion.set_comment(request.POST.get('commit_message'))


            Supporter(initiative=ini, user=request.user, initiator=True, ack=True, public=True).save()
            return redirect('/initiative/{}-{}'.format(ini.id, ini.slug))
        else:
            messages.warning(request, _("Please correct the following problems:"))

    return render(request, 'initproc/new.html', context=dict(form=form))

#@states_required(raise_exception=True)
#@can_access_initiative()
def item(request, init, slug=None):

    ctx = dict(initiative=init,
               user_count=init.eligible_voter_count,
               proposals=[x for x in init.proposals.prefetch_related('likes').all()],
               arguments=[x for x in init.pros.prefetch_related('likes').all()] +\
                         [x for x in init.contras.prefetch_related('likes').all()])

    ctx['arguments'].sort(key=lambda x: (-x.likes.count(), x.created_at))
    ctx['proposals'].sort(key=lambda x: (-x.likes.count(), x.created_at))

    ctx['is_likeable'] = request.guard.is_likeable (init)

    if request.user.is_authenticated:
        user_id = request.user.id

        ctx.update({'has_supported': init.supporting_initiative.filter(user=user_id).count()})

        votes = init.votes.filter(user=user_id)
        if (votes.exists()):
            ctx['vote'] = votes.first()

        for arg in ctx['arguments'] + ctx['proposals']:
            _personalize_argument(arg, user_id)

    print(ctx)
    return render(request, 'initproc/item.html', context=ctx)


@ajax
#@can_access_initiative()
def show_resp(request, initiative, target_type, target_id, slug=None):

    model_cls = apps.get_model('initproc', target_type)
    arg = get_object_or_404(model_cls, pk=target_id)

    assert arg.initiative == initiative, "How can this be?"

    ctx = dict(argument=arg,
               has_commented=False,
               is_likeable=request.guard.is_likeable(arg),
               full=param_as_bool(request.GET.get('full', 0)),
               comments=arg.comments.order_by('created_at').prefetch_related('likes').all())

    if request.user.is_authenticated:
        _personalize_argument(arg, request.user.id)
        for cmt in ctx['comments']:
            cmt.has_liked = cmt.likes.filter(user=request.user).exists()

    template = 'fragments/argument/item.html'


    return {'fragments': {
        '#{arg.type}-{arg.id}'.format(arg=arg): render_to_string(template,
                                                                 context=ctx, request=request)
        }}

@ajax
@login_required
#@can_access_initiative(None, 'can_moderate')
def show_moderation(request, initiative, target_id, slug=None):
    arg = get_object_or_404(Moderation, pk=target_id)

    assert arg.initiative == initiative, "How can this be?"

    ctx = dict(m=arg,
               has_commented=False,
               has_liked=False,
               is_likeable=True,
               full=1,
               comments=arg.comments.order_by('created_at').all())

    if request.user:
        ctx['has_liked'] = arg.likes.filter(user=request.user).exists()
        if arg.user == request.user:
            ctx['has_commented'] = True

    return {'fragments': {
        '#{arg.type}-{arg.id}'.format(arg=arg): render_to_string('fragments/moderation/item.html',
                                                                 context=ctx, request=request)
        }}


#
#      ___       ______ .___________. __    ______   .__   __.      _______.
#     /   \     /      ||           ||  |  /  __  \  |  \ |  |     /       |
#    /  ^  \   |  ,----'`---|  |----`|  | |  |  |  | |   \|  |    |   (----`
#   /  /_\  \  |  |         |  |     |  | |  |  |  | |  . `  |     \   \    
#  /  _____  \ |  `----.    |  |     |  | |  `--'  | |  |\   | .----)   |   
# /__/     \__\ \______|    |__|     |__|  \______/  |__| \__| |_______/    
#
#
#                                                                        

# ----------------------------- Undo action ------------------------------------
@login_required
@policy_state_access()
def policy_undo(request, policy, slug, uidb64, token):
  tokeniser = UndoUrlTokenGenerator()
  undo_state, undo_error = tokeniser.validate_token(request.user, "/".join([uidb64, token])) 
  
  if undo_state is None:
    messages.warning(request, "".join([_("Undo not possible. Please contact the Policy team in case you require assistance. Error:"), undo_error]))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))

  with reversion.create_revision():
    policy.state = undo_state
    policy.save()

    reversion.set_user(request.user)
    messages.success(request, _("Reverted to previous state."))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))


# ---------------------------- Policy Invite -----------------------------------
@ajax
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_STATE_DICT.STAGED)
@simple_form_verifier(InviteUsersForm, submit_title=_("Invite"))
def policy_invite(request, form, policy, invite_type, *args, **kwargs):

  if not request.guard.policy_edit(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("home")

  # skip ourselves,nothing to do if sufficient amount of co-initiators reached
  for user in form.cleaned_data["user"]:
    if user == request.user:
      continue
    if invite_type == 'initiators' and \
        policy.supporting_policy.filter(initiator=True).count() >= INITIATORS_COUNT:
        break

    # XXX maybe supporting_supporter is not such a good choice
    try:
      supporting_supporter = policy.supporting_policy.get(user_id=user.id)
    except Supporter.DoesNotExist:
      supporting_supporter = Supporter(user=user, policy=policy, ack=False)

      if invite_type == "initiators":
        supporting_supporter.initiator = True
      elif invite_type == "supporters":
        supporting_supporter.first = True

    # XXX indent - where does this belong to?
    # ? only allow promoting of supporters to initiators not downwards
    else:
      if invite_type == "initiators" and not supporting_supporter.initiator:
        supporting_supporter.initiator = True
        supporting_supporter.first = False
        supporting_supporter.ack = False
      else:
        continue

    supporting_supporter.save()
    notify([user], settings.NOTIFICATIONS.PUBLIC.POLICY_SUPPORT_INVITE, {
      "target": policy,
      "description": "".join([
        _("Invitation to support Policy:"),
        " ",
        policy.title
      ])
      }, sender=request.user)

  messages.success(request, _("Co-Initiators invited.") if invite_type == "initiators" else _("Supporters invited."))
  return redirect("/policy/{}-{}".format(policy.id, policy.slug))

# -------------------------- Policy Acknowledge Support ------------------------
@require_POST
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_EDIT_STATE_LIST)
def policy_acknowledge_support(request, policy, *args, **kwargs):
  user = request.user
  user_id = user.id
  ack_supporter = get_object_or_404(Supporter, policy=policy, user_id=user_id)
  ack_supporter.ack = True
  ack_supporter.save()

  # only inform if co-initiator signed on
  if ack_supporter.initiator == True:
    notify(
      [supporter.user for _, supporter in enumerate(policy.supporting_policy.filter(initiator=True).exclude(id=user_id))], 
      settings.NOTIFICATIONS.PUBLIC.POLICY_SUPPORT_ACCEPTED,
      {"description": "".join([user.first_name, " ", user.last_name, _(" confirmed to be co-initiator on policy: "), policy.title])},
      sender=user
    )

  messages.success(request, _("Thank you for the confirmation."))
  return redirect("/policy/{}".format(policy.id))

# ---------------------------- Policy Remove Support ---------------------------
@require_POST
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_EDIT_STATE_LIST)
def policy_remove_support(request, policy, *args, **kwargs):
  user = request.user
  user_id = user.id
  rm_supporter = get_object_or_404(Supporter, policy=policy, user_id=user_id)
  
  if rm_supporter.initiator == True:
    notify(
      [supporter.user for _, supporter in enumerate(policy.supporting_policy.filter(initiator=True).exclude(id=user_id))], 
      settings.NOTIFICATIONS.PUBLIC.POLICY_SUPPORT_REJECTED,
      {"description": "".join([user.first_name, " ", user.last_name, _(" resigned as co-initiator of policy: "), policy.title])},
      sender=user
    )

  rm_supporter.delete()
  messages.success(request, _("Your support has been retracted."))
  if policy.state == settings.PLATFORM_POLICY_STATE_DICT.VALIDATED:
    return redirect("/policy/{}".format(policy.id))
  return redirect("home")

# ---------------------------- Policy Stage ------------------------------------
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_STATE_DICT.DRAFT)
def policy_stage(request, policy, *args, **kwargs):

  if not request.guard.policy_edit(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("home")

  with reversion.create_revision():
    policy.state = settings.PLATFORM_POLICY_STATE_DICT.STAGED
    policy.staged_at = datetime.now()
    policy.save()

    reversion.set_user(request.user)

    messages.success(request, _("Policy moved to public status 'Staged'. It is now possible to invite co-initiators and supporters."))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))

# --------------------------------- Policy Delete ------------------------------
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_DELETE_STATE_LIST)
def policy_delete(request, policy, *args, **kwargs):

  if not request.guard.policy_edit(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("home")

  if not request.guard.policy_delete(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))

  with reversion.create_revision():
    user = request.user
    tokeniser = UndoUrlTokenGenerator()
    revert_url = "/policy/{}-{}/undo/{}".format(policy.id, policy.slug, tokeniser.create_token(user, policy))
    revert_message = "Policy deleted. <a href='%s'>%s</a>." % (revert_url, _("Click here to UNDO."))
    policy.state = settings.PLATFORM_POLICY_STATE_DICT.DELETED
    policy.save()

    reversion.set_user(user)
    messages.success(request, mark_safe(revert_message))
    return redirect('/policy/{}-{}'.format(policy.id, policy.slug))

# ------------------------------- Policy Undelete ------------------------------
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_STATE_DICT.DELETED)
def policy_undelete(request, policy, *args, **kwargs):

  if not request.guard.policy_undelete(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))

  with reversion.create_revision():
    policy.state = settings.PLATFORM_POLICY_STATE_DICT.HIDDEN
    policy.save()

    reversion.set_user(request.user)
    messages.success(request, _("Policy moved to hidden status. Unhide to put it back in Draft."))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))

# ------------------------------- Policy Unhide ------------------------------
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_STATE_DICT.HIDDEN)
def policy_unhide(request, policy, *args, **kwargs):

  if not request.guard.policy_unhide(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))

  with reversion.create_revision():
    policy.state = settings.PLATFORM_POLICY_STATE_DICT.DRAFT
    policy.save()

    reversion.set_user(request.user)
    messages.success(request, _("Policy moved to draft status. It can now be edited again by users."))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))

# ------------------------------- Policy Submit --------------------------------
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_STATE_DICT.STAGED)
def policy_submit(request, policy, *args, **kwargs):

  if not request.guard.policy_submit(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))

  with reversion.create_revision():
    user = request.user
    tokeniser = UndoUrlTokenGenerator()
    revert_url = "/policy/{}-{}/undo/{}".format(policy.id, policy.slug, tokeniser.create_token(user, policy))
    revert_message = "Policy submitted. Policy submitted for moderation. You will receive a message once feedback on the Policy is availble. <a href='%s'>%s</a>." % (revert_url, _("Click here to UNDO."))
    policy.state = settings.PLATFORM_POLICY_STATE_DICT.SUBMITTED
    policy.save()

    # make sure moderation starts from the top
    policy.policy_moderations.update(stale=True)

    # XXX how to handle UNDO? sleep?
    # notifiy initiators
    supporters = policy.supporting_policy.filter(initiator=True).exclude(user_id=user.id)
    notify(
      [supporter.user for _, supporter in enumerate(supporters)],
      settings.NOTIFICATIONS.PUBLIC.POLICY_SUBMITTED, {
        "description": "".join([_("Policy submitted:"), " ", policy.title, ". ", _("Awaiting moderation.")])
      }, sender=user
    )

    # notify policy team with moderation permission

    reversion.set_user(request.user)
    messages.success(request, mark_safe(revert_message))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))

# ----------------------------- Policy Validate --------------------------------
# used to be for incoming and moderation (submit and release)
# every validation is a review, once the required number of reviews are in,
# any moderator can manually validate a proposal into seeksupport/discussion
@ajax
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_MODERATION_STATE_LIST)
@simple_form_verifier(NewModerationForm, submit_title=_("Add validation review."))
def policy_review(request, form, policy, *args, **kwargs):

  if request.guard.policy_validate(policy):
    user = request.user
    moderation = form.save(commit=False)
    moderation.policy = policy
    moderation.user = user
    moderation.save()

    # XXX r like reject is a bad choice to request (more info)
    if moderation.vote == "r":
      policy.state = settings.PLATFORM_POLICY_STATE_DICT.INVALIDATED
      policy.save()

    if policy.ready_for_next_stage:
      policy.supporting_policy.filter(ack=False).delete()
      policy.was_validated_at = datetime.now()
      policy.state = settings.PLATFORM_POLICY_STATE_DICT.VALIDATED
      policy.save()
  
      messages.success(request, _("Policy validated."))
  
      # we can inform all supporters, because there is only initiators
      supporters = policy.supporting_policy.all().exclude(user_id=user.id)
      notify(
        [supporter.user for _, supporter in enumerate(supporters)],
        settings.NOTIFICATIONS.PUBLIC.POLICY_VALIDATED, {
          "description": "".join([_("Policy validated:"), " ", policy.title, ". "])
          }
        )
      
      notify(
        [moderation.user for moderation in policy.policy_moderations.all()],
        settings.NOTIFICATIONS.PUBLIC.POLICY_VALIDATED, {
          "description": "".join([_("Policy validated:"), " ", policy.title, ". "])
          }, sender=user
        )
    else:
      messages.success(request, _("Validation review recorded."))
    return redirect('/policy/{}'.format(policy.id))

  # XXX used to be here, move to release
  #if request.guard.policy_release(policy):
  #  policy_to_release = [policy]
  #
  #  # check the variants, too
  #  if policy.all_variants:
  #    for variant in policy.all_variants:
  #      if variant.state != STATES.MODERATION or not request.guard.can_publish(ini):
  #        policy_to_release = None
  #          break
  #      policy_to_release.append(variant)
  #
  #      if policy_to_release:
  #        for releaseable_policy in policy_to_release:
  #          releasable_policy.went_to_voting_at = datetime.now()
  #          releasable_policy.state = STATES.VOTING
  #          releasable_policy.save()
  #          releasable_policy.notify_followers(settings.NOTIFICATIONS.PUBLIC.WENT_TO_VOTE)
  #          releasable_policy.notify_moderators(settings.NOTIFICATIONS.PUBLIC.WENT_TO_VOTE, subject=request.user)
  #
  #        messages.success(request, _("Initiative activated for Voting."))
  #        return redirect('/initiative/{}-{}'.format(initiative.id, initiative.slug))


  return {
    "inner-fragments": {"#moderation-new": "".join(["<strong>", _("Validation review registered"), "</strong>"])},
    "append-fragments": {
      "#moderation-list": render_to_string(
        "fragments/moderation/item.html",
        context=dict(m=moderation, policy=policy, full=0),
        request=request
      )
    }
  }

# ----------------------------- Target Comment  ---------------------------------
@non_ajax_redir('/')
@ajax
@login_required
@simple_form_verifier(NewCommentForm, cancel=True, cancel_template="fragments/comment/comment_add.html")
def target_comment(request, form, target_type, target_id, *args, **kwargs):

  model_class = apps.get_model('initproc', target_type)
  target_object = get_object_or_404(model_class, pk=target_id)

  # do this in the template BEFORE making the Ajax request, else user writes his
  # comment and then gets permission denied.
  #if not request.guard.target_comment(target_object):
  #  raise PermissionDenied()

  data = form.cleaned_data
  new_comment = Comment(target=target_object, user=request.user, **data)
  new_comment.save()

  return {
    "inner-fragments": {
      "#{}-new-comment".format(target_object.unique_id): "".join(["<strong>", _("Thank you for your comment."), "</strong>"]),

      # This user has now commented, so fill in the chat icon
      "#{}-chat-icon".format(target_object.unique_id): "chat_bubble",
      "#{}-comment-count".format(target_object.unique_id): target_object.comments.count()
    },
    "append-fragments": {
      "#{}-comment-list".format(target_object.unique_id): render_to_string(
        "fragments/comment/item.html",
        context=dict(comment=new_comment),
        request=request
      )
    }
  }

# ----------------------------- Target Cancel  ---------------------------------
# XXX do this in regex once figuring out how to match with &cancel=True...
#@non_ajax_redir('/')
#@ajax
#@login_required
#def target_cancel(request, target_type, target_id, *args, **kwargs):
#  return target_comment(request, target_type, target_id, *args, **kwargs)

# ------------------------------ Target Like -----------------------------------
@non_ajax_redir('/')
@ajax
@login_required
def target_like(request, target_type, target_id):

  model_class = apps.get_model('initproc', target_type)
  target_object = get_object_or_404(model_class, pk=target_id)

  if not request.guard.can_like(target_object):
    raise PermissionDenied()

  if not request.guard.is_likeable(target_object):
    raise PermissionDenied()

  fake_context = {
    "target": target_object,
    "with_link": True,
    "show_text": False,
    "show_count": True,
    "has_liked": True,
    "is_likeable": True
  }

  for key in ['show_text', 'show_count']:
    if key in request.GET:
      fake_context[key] = param_as_bool(request.GET[key])

  Like(target=target_object, user=request.user).save()

  return {
    "fragments": {
      ".{}-like".format(target_object.unique_id): render_to_string(
        "fragments/like.html",
        context=fake_context,
        request=request
      )
    },
    "inner-fragments": {
      ".{}-like-icon".format(target_object.unique_id): "favorite",
      ".{}-like-count".format(target_object.unique_id): target_object.likes.count(),
    }
  }

# ----------------------------- Target Unlike ----------------------------------
@non_ajax_redir('/')
@ajax
@login_required
def target_unlike(request, target_type, target_id):

  model_class = apps.get_model('initproc', target_type)
  target_object = get_object_or_404(model_class, pk=target_id)

  if not request.guard.is_likeable(target_object):
    raise PermissionDenied()

  target_object.likes.filter(user_id=request.user.id).delete()

  fake_context = {
    "target": target_object,
    "with_link": True,
    "show_text": False,
    "show_count": True,
    "has_liked": False,
    "is_likeable": True
  }

  for key in ['show_text', 'show_count']:
    if key in request.GET:
        fake_context[key] = param_as_bool(request.GET[key])

  return {
    "fragments": {
      ".{}-like".format(target_object.unique_id): render_to_string(
        "fragments/like.html",
        context=fake_context,
        request=request
      )
    },
    "inner-fragments": {
      ".{}-like-icon".format(target_object.unique_id): "favorite_border",
      ".{}-like-count".format(target_object.unique_id): target_object.likes.count(),
    }
  }

# ----------------------------- Target Edit ----------------------------------
@non_ajax_redir('/')
@ajax
@login_required
def target_edit(request, target_type, target_id):

  model_class = apps.get_model('initproc', target_type)
  target_object = get_object_or_404(model_class, pk=target_id)

  if not request.guard.is_likeable(target_object):
    raise PermissionDenied()

  if not request.guard.is_modifyable(target_object):
    raise PermissionDenied()

  data = form.cleaned_data
  new_comment = Comment(target=target_object, user=request.user, **data)
  new_comment.save()

  fake_context = {
    "target": target_object,
    "with_link": True,
    "show_text": False,
    "show_count": True,
    "has_liked": False,
    "is_likeable": True
  }

  for key in ['show_text', 'show_count']:
    if key in request.GET:
        fake_context[key] = param_as_bool(request.GET[key])

  return {
    "fragments": {
      ".{}-like".format(target_object.unique_id): render_to_string(
        "fragments/like.html",
        context=fake_context,
        request=request
      )
    },
    "inner-fragments": {
      ".{}-like-icon".format(target_object.unique_id): "favorite_border",
      ".{}-like-count".format(target_object.unique_id): target_object.likes.count(),
    }
  }

# ----------------------------- Target Delete ----------------------------------
@non_ajax_redir('/')
@ajax
@login_required
def target_delete(request, target_type, target_id):

  model_class = apps.get_model('initproc', target_type)
  target_object = get_object_or_404(model_class, pk=target_id)

  if not request.guard.is_likeable(target_object):
    raise PermissionDenied()

  if not request.guard.is_modifyable(target_object):
    raise PermissionDenied()

  target_object.delete()
  messages.success(request, _("Comment deleted."))
  
  return {
    "inner-fragments": {
      "#{}-new-comment".format(target_object.unique_id): "".join(["<strong>", _("Thank you for your comment."), "</strong>"]),

      # This user has now commented, so fill in the chat icon
      "#{}-chat-icon".format(target_object.unique_id): "chat_bubble",
      "#{}-comment-count".format(target_object.unique_id): target_object.comments.count()
    },
    "append-fragments": {
      "#{}-comment-list".format(target_object.unique_id): render_to_string(
        "fragments/comment/item.html",
        context=dict(comment=new_comment),
        request=request
      )
    }
  }
  #target_object.likes.filter(user_id=request.user.id).delete()
  #
  #fake_context = {
  #  "target": target_object,
  #  "with_link": True,
  #  "show_text": False,
  #  "show_count": True,
  #  "has_liked": False,
  #  "is_likeable": True
  #}
  #
  #for key in ['show_text', 'show_count']:
  #  if key in request.GET:
  #      fake_context[key] = param_as_bool(request.GET[key])
  #
  #return {
  #  "fragments": {
  #    ".{}-like".format(target_object.unique_id): render_to_string(
  #      "fragments/like.html",
  #      context=fake_context,
  #      request=request
  #    )
  #  },
  #  "inner-fragments": {
  #    ".{}-like-icon".format(target_object.unique_id): "favorite_border",
  #    ".{}-like-count".format(target_object.unique_id): target_object.likes.count(),
  #  }
  #}






@login_required
#@can_access_initiative([STATES.PREPARE, STATES.FINAL_EDIT], 'can_edit')
def submit_to_committee(request, initiative):
    if initiative.ready_for_next_stage:
        initiative.state = STATES.INCOMING if initiative.state == STATES.PREPARE else STATES.MODERATION
        initiative.save()

        # make sure moderation starts from the top
        initiative.moderations.update(stale=True)

        messages.success(request, _("The Initiative was received and is being validated."))
        initiative.notify_initiators(settings.NOTIFICATIONS.PUBLIC.POLICY_SUBMITTED, subject=request.user)
        # To notify the review team, we notify all members of groups with moderation permission,
        # which doesn't include superusers, though they individually have moderation permission.
        moderation_permission = Permission.objects.filter(content_type__app_label='initproc', codename='add_moderation')
        initiative.notify(get_user_model().objects.filter(groups__permissions=moderation_permission, is_active=True).all(),
                          settings.NOTIFICATIONS.PUBLIC.POLICY_SUBMITTED, subject=request.user)
        return redirect('/initiative/{}'.format(initiative.id))
    else:
        messages.warning(request, _("The requirements for submission have not been met."))

    return redirect('/initiative/{}'.format(initiative.id))

@login_required
#@can_access_initiative([STATES.PREPARE, STATES.FINAL_EDIT], 'can_edit')
def edit(request, initiative):
    form = InitiativeForm(request.POST or None, instance=initiative)
    if request.method == 'POST':
        if form.is_valid():
            with reversion.create_revision():
                initiative.save()

                # Store some meta-information.
                reversion.set_user(request.user)
                if request.POST.get('commit_message', None):
                    reversion.set_comment(request.POST.get('commit_message'))

            initiative.supporting_initiative.filter(initiator=True).update(ack=False)

            messages.success(request, _("Initiative saved."))
            initiative.notify_followers(settings.NOTIFICATIONS.PUBLIC.POLICY_EDITED, subject=request.user)
            return redirect('/initiative/{}'.format(initiative.id))
        else:
            messages.warning(request, _("Please correct the following problems:"))

    return render(request, 'initproc/new.html', context=dict(form=form, initiative=initiative))



@ajax
@login_required
#@can_access_initiative(STATES.PREPARE, 'can_edit') 
@simple_form_verifier(InviteUsersForm, submit_title=_("Invite"))
def invite(request, form, initiative, invite_type):
    for user in form.cleaned_data['user']:
        if user == request.user: continue # we skip ourselves
        if invite_type == 'initiators' and \
            initiative.supporting_initiative.filter(initiator=True).count() >= INITIATORS_COUNT:
            break

        # XXX: supporting = initiative.supporting is confusing?
        try:
            supporting_supporter = initiative.supporting_initiative.get(user_id=user.id)
        except Supporter.DoesNotExist:
            supporting_supporter = Supporter(user=user, initiative=initiative, ack=False)

            if invite_type == 'initiators':
                supporting_supporter.initiator = True
            elif invite_type == 'supporters':
                supporting_supporter.first = True
        else:
            if invite_type == 'initiators' and not supporting_supporter.initiator:
                # we only allow promoting of supporters to initiators
                # not downwards.
                supporting_supporter.initiator = True
                supporting_supporter.first = False
                supporting_supporter.ack = False
            else:
                continue
        
        supporting_supporter.save()

        notify([user], settings.NOTIFICATIONS.PUBLIC.POLICY_SUPPORT_INVITE, {"target": initiative}, sender=request.user)

    messages.success(request, _("Initiators invited.") if invite_type == 'initiators' else _("Supporters invited."))
    return redirect("/initiative/{}-{}".format(initiative.id, initiative.slug))



@login_required
#@can_access_initiative(STATES.SEEKING_SUPPORT, 'can_support') # must be seeking for supporters
def support(request, initiative):
    Supporter(initiative=initiative, user_id=request.user.id,
              public=not not request.GET.get("public", False)).save()

    return redirect('/initiative/{}'.format(initiative.id))


@require_POST
@login_required
#@can_access_initiative([STATES.PREPARE, STATES.INCOMING, STATES.FINAL_EDIT])
def ack_support(request, initiative):
    sup = get_object_or_404(Supporter, initiative=initiative, user_id=request.user.id)
    sup.ack = True
    sup.save()

    messages.success(request, _("Thank you for the confirmation"))
    initiative.notify_initiators(settings.NOTIFICATIONS.PUBLIC.POLICY_SUPPORT_ACCEPTED, subject=request.user)

    return redirect('/initiative/{}'.format(initiative.id))


@require_POST
@login_required
#@can_access_initiative([STATES.SEEKING_SUPPORT, STATES.INCOMING, STATES.PREPARE])
def rm_support(request, initiative):
    sup = get_object_or_404(Supporter, initiative=initiative, user_id=request.user.id)
    sup.delete()

    messages.success(request, _("Your support has been retracted"))
    initiative.notify_initiators(settings.NOTIFICATIONS.PUBLIC.POLICY_SUPPORT_REJECTED, subject=request.user)

    if initiative.state == 's':
        return redirect('/initiative/{}'.format(initiative.id))
    return redirect('/')


@non_ajax_redir('/')
@ajax
@login_required
#@can_access_initiative(STATES.DISCUSSION) # must be in discussion
@simple_form_verifier(NewArgumentForm, template="fragments/argument/new.html")
def new_argument(request, form, initiative):
    data = form.cleaned_data
    argCls = Pro if data['type'] == "👍" else Contra

    arg = argCls(initiative=initiative,
                 user_id=request.user.id,
                 title=data['title'],
                 text=data['text'])

    arg.save()

    initiative.notify_followers(settings.NOTIFICATIONS.PUBLIC.NEW_ARGUMENT, dict(argument=arg), subject=request.user)

    return {
        'fragments': {'#no-arguments': ""},
        'inner-fragments': {'#new-argument': render_to_string("fragments/argument/thumbs.html",
                                                  context=dict(initiative=initiative)),
                            '#debate-thanks': render_to_string("fragments/argument/argument_thanks.html"),
                            '#debate-count': initiative.pros.count() + initiative.contras.count()},
        'append-fragments': {'#argument-list': render_to_string("fragments/argument/item.html",
                                                  context=dict(argument=arg,full=0),
                                                  request=request)}
    }



@non_ajax_redir('/')
@ajax
@login_required
#@can_access_initiative(STATES.DISCUSSION) # must be in discussion
@simple_form_verifier(NewProposalForm)
def new_proposal(request, form, initiative):
    data = form.cleaned_data
    proposal = Proposal(initiative=initiative,
                        user_id=request.user.id,
                        title=data['title'],
                        text=data['text'])

    proposal.save()

    return {
        'fragments': {'#no-proposals': ""},
        'inner-fragments': {'#new-proposal': render_to_string("fragments/argument/propose.html",
                                                  context=dict(initiative=initiative)),
                            '#proposals-thanks': render_to_string("fragments/argument/proposal_thanks.html"),
                            '#proposals-count': initiative.proposals.count()},
        'append-fragments': {'#proposal-list': render_to_string("fragments/argument/item.html",
                                                  context=dict(argument=proposal,full=0),
                                                  request=request)}
    }


@ajax
@login_required
#@can_access_initiative([STATES.INCOMING, STATES.MODERATION], 'can_moderate') # must be in discussion
@simple_form_verifier(NewModerationForm)
def moderate(request, form, initiative):
    model = form.save(commit=False)
    model.initiative = initiative
    model.user = request.user
    model.save()

    if request.guard.can_publish(initiative):
        if initiative.state == STATES.INCOMING:
            initiative.supporting_initiative.filter(ack=False).delete()
            initiative.went_public_at = datetime.now()
            initiative.state = STATES.SEEKING_SUPPORT
            initiative.save()

            messages.success(request, _("Initiative published"))
            initiative.notify_followers(settings.NOTIFICATIONS.PUBLIC.POLICY_PUBLISHED)
            initiative.notify_moderators(settings.NOTIFICATIONS.PUBLIC.POLICY_PUBLISHED, subject=request.user)
            return redirect('/initiative/{}'.format(initiative.id))

        elif initiative.state == STATES.MODERATION:

            publish = [initiative]
            if initiative.all_variants:
                # check the variants, too

                for ini in initiative.all_variants:
                    if ini.state != STATES.MODERATION or not request.guard.can_publish(ini):
                        publish = None
                        break
                    publish.append(ini)

            if publish:
                for init in publish:
                    init.went_to_voting_at = datetime.now()
                    init.state = STATES.VOTING
                    init.save()
                    init.notify_followers(settings.NOTIFICATIONS.PUBLIC.WENT_TO_VOTE)
                    init.notify_moderators(settings.NOTIFICATIONS.PUBLIC.WENT_TO_VOTE, subject=request.user)

                messages.success(request, _("Initiative activated for Voting."))
                return redirect('/initiative/{}-{}'.format(initiative.id, initiative.slug))


    
    return {
        'fragments': {'#no-moderations': ""},
        'inner-fragments': {'#moderation-new': "".join(["<strong>", _("Entry registered"), "</strong>"])},
        'append-fragments': {'#moderation-list': render_to_string("fragments/moderation/item.html",
                                                  context=dict(m=model,initiative=initiative,full=0),
                                                  request=request)}
    }



@non_ajax_redir('/')
@ajax
@login_required
@simple_form_verifier(NewCommentForm)
def comment(request, form, target_type, target_id):
    model_cls = apps.get_model('initproc', target_type)
    model = get_object_or_404(model_cls, pk=target_id)

    if not request.guard.can_comment(model):
        raise PermissionDenied()


    data = form.cleaned_data
    cmt = Comment(target=model, user=request.user, **data)
    cmt.save()

    return {
        'inner-fragments': {'#{}-new-comment'.format(model.unique_id):
                "".join(["<strong>", _("Thank you for your comment."), "</strong>"]),
                '#{}-chat-icon'.format(model.unique_id):
                "chat_bubble", # This user has now commented, so fill in the chat icon
                '#{}-comment-count'.format(model.unique_id):
                model.comments.count()},
        'append-fragments': {'#{}-comment-list'.format(model.unique_id):
            render_to_string("fragments/comment/item.html",
                             context=dict(comment=cmt),
                             request=request)}
    }


@non_ajax_redir('/')
@ajax
@login_required
@require_POST
#@can_access_initiative(STATES.VOTING) # must be in voting
def vote(request, init):
    voted_value = request.POST.get('voted')
    if voted_value == 'no':
        voted = VOTED.NO
    elif voted_value == "yes":
        voted = VOTED.YES
    else:
        voted = VOTED.ABSTAIN


    reason = request.POST.get("reason", "")
    try:
        my_vote = Vote.objects.get(initiative=init, user_id=request.user)
    except Vote.DoesNotExist:
        my_vote = Vote(initiative=init, user_id=request.user.id, value=voted)
    else:
        my_vote.voted = voted
        my_vote.reason = reason
    my_vote.save()

    return get_voting_fragments(my_vote, init, request)



@non_ajax_redir('/')
@ajax
#@can_access_initiative()
def compare(request, initiative, version_id):
    versions = Version.objects.get_for_object(initiative)
    latest = versions.first()
    selected = versions.filter(id=version_id).first()
    compare = {key: mark_safe(html_diff(selected.field_dict.get(key, ''),
                                        latest.field_dict.get(key, '')))
            for key in COMPARING_FIELDS}

    compare['went_public_at'] = initiative.went_public_at


    return {
        'inner-fragments': {
            'header': "",
            '.main': render_to_string("fragments/compare.html",
                                      context=dict(initiative=initiative,
                                                    selected=selected,
                                                    latest=latest,
                                                    compare=compare),
                                      request=request)}
    }



@non_ajax_redir('/')
@ajax
@login_required
@require_POST
#@can_access_initiative(STATES.VOTING) # must be in voting
def reset_vote(request, init):
    Vote.objects.filter(initiative=init, user_id=request.user).delete()
    return get_voting_fragments(None, init, request)
