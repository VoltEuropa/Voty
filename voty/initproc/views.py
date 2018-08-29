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
from reversion_compare.helpers import html_diff
from reversion.models import Version
import reversion

from functools import wraps
import json

from .globals import STATES, VOTED, INITIATORS_COUNT, COMPARING_FIELDS
from .models import (Policy, Initiative, Pro, Contra, Proposal, Comment, Vote, Moderation, Quorum, Supporter, Like)
from .forms import (simple_form_verifier, PolicyForm, InitiativeForm, NewArgumentForm, NewCommentForm,
                    NewProposalForm, NewModerationForm, InviteUsersForm)
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


# --------------------- State Permission decorator -----------------------------
# moved here from guard.py
def policy_state_access(states=None):
  def wrap(fn):
    def view(request, policy_id, slug, *args, **kwargs):
      policy = get_object_or_404(Policy, pk=policy_id)

      if policy is None:
        message.warning(request, _("Policy not found"))
        return redirect(request, "")

      if states:
        assert policy.state in states, "{} Not in expected state: {}".format(policy.state, states)

      # NOTE: this adds the policy on the request
      request.policy = policy
      return fn(request, policy, *args, **kwargs)
    return view
  return wrap

# --------------------------- personalise arguments ----------------------------
def personalize_argument(arg, user_id):
  arg.has_liked = arg.likes.filter(user=user_id).exists()
  arg.has_commented = arg.comments.filter(user__id=user_id).exists()

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
    return redirect("")

  payload = dict(
    policy=policy,
    user_count=policy.eligible_voter_count,
    policy_proposals=[x for x in policy.policy_proposals.prefetch_related("likes").all()],
    policy_arguments=[x for x in policy.policy_pros.prefetch_related('likes').all()] + \
      [x for x in policy.policy_contras.prefetch_related("likes").all()]
  )

  payload["policy_arguments"].sort(key=lambda x: (-x.policy_likes.count(), x.created_at))
  payload["policy_proposals"].sort(key=lambda x: (-x.policy_likes.count(), x.created_at))
  payload["is_editable"] = request.guard.is_editable (policy)

  # personalise if authenticated user interacted with policy
  if request.user.is_authenticated:
    user_id = request.user.id
    payload.update({"has_supported": policy.supporting_policy.filter(user=user_id).count()})
    policy_votes = policy.policy_votes.filter(user=user_id)
    if (policy_votes.exists()):
      payload['policy_vote'] = policy_votes.first()
    for arg in payload['policy_arguments'] + payload['policy_proposals']:
      personalize_argument(arg, user_id)

  return render(request, 'initproc/policy_item.html', context=payload)

# ----------------------------- Policy Edit ------------------------------------
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_EDIT_STATE_LIST)
def policy_edit(request, policy, *args, **kwargs):

  if not request.guard.policy_view(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("/")

  if not request.guard.policy_edit(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("/")

  form = PolicyForm(request.POST or None, instance=policy)
  if request.method == 'POST':
    user = request.user
    if form.is_valid():
      with reversion.create_revision():
        policy.save()
        reversion.set_user(user)

      # keep asking initial supporters to repledge?
      policy.supporting_initiative.filter(initiator=True).exclude(id=user.id).update(ack=False)
      policy.notify_followers(settings.NOTIFICATIONS.PUBLIC.EDITED, subject=user)
      messages.success(request, _("Policy updated."))
      return redirect("/policy/{}".format(policy.id))
    else:
      messages.warning(request, _("Please correct the following problems:"))

  return render(request, "initproc/policy_edit.html", context=dict(form=form, policy=policy))

# ----------------------------- Policy New -------------------------------------
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

      Supporter(policy=policy_object, user=user, initiator=True, ack=True, public=True).save()
      messages.success(request, _("Created new Policy draft."))
      return redirect('/policy/{}-{}'.format(policy_object.id, policy_object.slug))
    else:
      messages.warning(request, _("Please fill out all required fields."))

  return render(request, 'initproc/policy_edit.html', context=dict(form=form))





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

    ctx['is_editable'] = request.guard.is_editable (init)

    if request.user.is_authenticated:
        user_id = request.user.id

        ctx.update({'has_supported': init.supporting_initiative.filter(user=user_id).count()})

        votes = init.votes.filter(user=user_id)
        if (votes.exists()):
            ctx['vote'] = votes.first()

        for arg in ctx['arguments'] + ctx['proposals']:
            personalize_argument(arg, user_id)

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
               is_editable=request.guard.is_editable(arg),
               full=param_as_bool(request.GET.get('full', 0)),
               comments=arg.comments.order_by('created_at').prefetch_related('likes').all())

    if request.user.is_authenticated:
        personalize_argument(arg, request.user.id)
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
               is_editable=True,
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
            initiative.notify_followers(settings.NOTIFICATIONS.PUBLIC.EDITED, subject=request.user)
            return redirect('/initiative/{}'.format(initiative.id))
        else:
            messages.warning(request, _("Please correct the following problems:"))

    return render(request, 'initproc/new.html', context=dict(form=form, initiative=initiative))


@login_required
#@can_access_initiative([STATES.PREPARE, STATES.FINAL_EDIT], 'can_edit')
def submit_to_committee(request, initiative):
    if initiative.ready_for_next_stage:
        initiative.state = STATES.INCOMING if initiative.state == STATES.PREPARE else STATES.MODERATION
        initiative.save()

        # make sure moderation starts from the top
        initiative.moderations.update(stale=True)

        messages.success(request, _("The Initiative was received and is being validated."))
        initiative.notify_initiators(settings.NOTIFICATIONS.PUBLIC.SUBMITTED, subject=request.user)
        # To notify the review team, we notify all members of groups with moderation permission,
        # which doesn't include superusers, though they individually have moderation permission.
        moderation_permission = Permission.objects.filter(content_type__app_label='initproc', codename='add_moderation')
        initiative.notify(get_user_model().objects.filter(groups__permissions=moderation_permission, is_active=True).all(),
                          settings.NOTIFICATIONS.PUBLIC.SUBMITTED, subject=request.user)
        return redirect('/initiative/{}'.format(initiative.id))
    else:
        messages.warning(request, _("The requirements for submission have not been met."))

    return redirect('/initiative/{}'.format(initiative.id))



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

        notify([user], settings.NOTIFICATIONS.PUBLIC.SUPPORT_INVITE, {"target": initiative}, sender=request.user)

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
    initiative.notify_initiators(settings.NOTIFICATIONS.PUBLIC.SUPPORT_ACCEPTED, subject=request.user)

    return redirect('/initiative/{}'.format(initiative.id))


@require_POST
@login_required
#@can_access_initiative([STATES.SEEKING_SUPPORT, STATES.INCOMING, STATES.PREPARE])
def rm_support(request, initiative):
    sup = get_object_or_404(Supporter, initiative=initiative, user_id=request.user.id)
    sup.delete()

    messages.success(request, _("Your support has been retracted"))
    initiative.notify_initiators(settings.NOTIFICATIONS.PUBLIC.SUPPORT_REJECTED, subject=request.user)

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
            initiative.notify_followers(settings.NOTIFICATIONS.PUBLIC.PUBLISHED)
            initiative.notify_moderators(settings.NOTIFICATIONS.PUBLIC.PUBLISHED, subject=request.user)
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
def like(request, target_type, target_id):
    model_cls = apps.get_model('initproc', target_type)
    model = get_object_or_404(model_cls, pk=target_id)

    if not request.guard.can_like(model):
        raise PermissionDenied()

    if not request.guard.is_editable(model):
        raise PermissionDenied()

    ctx = {"target": model, "with_link": True, "show_text": False, "show_count": True, "has_liked": True, "is_editable": True}
    for key in ['show_text', 'show_count']:
        if key in request.GET:
            ctx[key] = param_as_bool(request.GET[key])

    Like(target=model, user=request.user).save()
    return {'fragments': {
        '.{}-like'.format(model.unique_id): render_to_string("fragments/like.html",
                                                             context=ctx,
                                                             request=request)
    }, 'inner-fragments': {
        '.{}-like-icon'.format(model.unique_id): 'favorite',
        '.{}-like-count'.format(model.unique_id): model.likes.count(),
    }}


@non_ajax_redir('/')
@ajax
@login_required
def unlike(request, target_type, target_id):
    model_cls = apps.get_model('initproc', target_type)
    model = get_object_or_404(model_cls, pk=target_id)

    if not request.guard.is_editable(model):
        raise PermissionDenied()

    model.likes.filter(user_id=request.user.id).delete()

    ctx = {"target": model, "with_link": True, "show_text": False, "show_count": True, "has_liked": False, "is_editable": True}
    for key in ['show_text', 'show_count']:
        if key in request.GET:
            ctx[key] = param_as_bool(request.GET[key])

    return {'fragments': {
        '.{}-like'.format(model.unique_id): render_to_string("fragments/like.html",
                                                             context=ctx,
                                                             request=request)
    }, 'inner-fragments': {
        '.{}-like-icon'.format(model.unique_id): 'favorite_border',
        '.{}-like-count'.format(model.unique_id): model.likes.count(),
    }}



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
