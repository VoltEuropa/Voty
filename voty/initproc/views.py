# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initproc views/actions
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.utils.decorators import available_attrs
from django.utils.safestring import mark_safe
from django.contrib.postgres.search import SearchVector
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.conf import settings
from django.apps import apps
from .filters import PolicyFilter
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

from .globals import STATES, INITIATORS_COUNT, COMPARING_FIELDS
from .models import (Policy, PolicyBase, Initiative, Pro, Contra, Proposal, Comment, Vote, Moderation, Quorum,
                     Supporter, Like)
from .forms import (PolicyForm, NewArgumentForm, NewCommentForm,
                    NewProposalForm, NewModerationForm, InviteUsersForm)
from .undo import UndoUrlTokenGenerator
from .serializers import SimpleInitiativeSerializer, SimplePolicySerializer
from django.contrib.auth.models import Permission
from django.utils.translation import ugettext as _

DEFAULT_FILTERS = [
    STATES.PREPARE,
    STATES.INCOMING,
    STATES.SEEKING_SUPPORT,
    STATES.DISCUSSION,
    STATES.VOTING]


# ============================= HELPERS ========================================

# XXX used/useful
def _non_ajax_redir(*redir_args, **redir_kwargs):
    def decorator(func):
        @wraps(func, assigned=available_attrs(func))
        def inner(request, *args, **kwargs):
            if not request.is_ajax():
                # we redirect you
                return redirect(*redir_args, **redir_kwargs)
            return func(request, *args, **kwargs)

        return inner

    return decorator


# I removed the emojis...
def _param_as_bool(param):
    try:
        return bool(int(param))
    except ValueError:
        return param.lower() in ['true', 'y', 'yes', 'j', 'ja' 'yay', 'yop', 'yope']


# for categories, display category translation not database-placeholder
def _get_policy_field_value(key, version, field_meta_dict):
    for f in field_meta_dict:
        if key == f.name:

            # XXX how to make this generic??? f.get_internal_type() == "CharField"?
            if key == "scope":
                return getattr(settings.CATEGORIES.SCOPE_DICT,
                               version.field_dict.get(key, '').upper().replace("-", "_"))
            elif key == "topic":
                return getattr(settings.CATEGORIES.TOPIC_DICT,
                               version.field_dict.get(key, '').upper().replace("-", "_"))
            elif key == "context":
                return getattr(settings.CATEGORIES.CONTEXT_DICT,
                               version.field_dict.get(key, '').upper().replace("-", "_"))
            else:
                return version.field_dict.get(key, '')


# like/unlike/edit/delete can be on a comment or moderation/proposal/pro/con
# comments have only a target-type/id, the others have policy_id defined
def _get_related_policy(target_object):
    parent_id = getattr(target_object, "policy_id", None)
    if parent_id:
        return _fetch_object_from_class("Policy", parent_id), None
    else:
        target_parent = _fetch_object_from_class(target_object.target_type.name, target_object.target_id)
        return _fetch_object_from_class("Policy", target_parent.policy_id), target_parent


# shortcut to retrieving object
def _fetch_object_from_class(target_type, target_id):
    return get_object_or_404(apps.get_model('initproc', target_type), pk=target_id)


# build a payload dict used throughout to render policy_item
def _generate_payload(policy):
    proposals = policy.policy_proposals.prefetch_related("likes").all()

    payload = dict(
        policy=policy,
        user_count=policy.eligible_voter_count,
        policy_proposals_active=[x for x in proposals.filter(stale=False)],
        policy_proposals_stale=[x for x in proposals.filter(stale=True)],
        policy_fields=[f.name for f in PolicyBase._meta.get_fields() if f.get_internal_type() == "TextField"],
        policy_arguments=[x for x in policy.policy_pros.prefetch_related('likes').all()] + \
                         [x for x in policy.policy_contras.prefetch_related("likes").all()],
    )

    payload["policy_proposals_stale_count"] = policy.policy_proposals.filter(stale=True)
    payload["policy_arguments"].sort(key=lambda x: (-x.likes.count(), x.created_at))
    payload["policy_proposals_active"].sort(key=lambda x: (-x.likes.count(), x.created_at))
    payload["policy_proposals_stale"].sort(key=lambda x: (-x.likes.count(), x.changed_at))

    return payload


# -------------------------- Simple Form Verifier ------------------------------
def simple_form_verifier(form_cls, template="fragments/simple_form.html", via_ajax=True,
                         submit_klasses="btn-outline-primary", submit_title=_("Send"),
                         cancel=None, cancel_template=None):
    def wrap(fn):
        def view(request, *args, **kwargs):
            cancel_url = target_object = None

            # try retrieving the target object (eg comment -> moderation)
            try:
                target_type = kwargs["target_type"]
                target_id = kwargs["target_id"]
            except (KeyError, AttributeError):
                target_type = request.GET.get("target_type")
                target_id = request.GET.get("target_id")

            # POST, should be forwarded to the respective action below
            if request.method == "POST":
                form = form_cls(request.POST)
                if form.is_valid():
                    return fn(request, form, *args, **kwargs)

            # GET
            else:
                if request.GET.get("edit"):
                    initial_dict = {}
                    target_object = target_object or _fetch_object_from_class(target_type, target_id)
                    for field in target_object._meta.get_fields():

                        # XXX shouldn't be here, but moderation tickboxes weren't stored
                        if field.name == "blockers":
                            blockers = (getattr(target_object, field.name) or "").split(",")
                            for blocker in blockers:
                                initial_dict[blocker] = True
                        else:
                            initial_dict[field.name] = getattr(target_object, field.name)
                    form = form_cls(initial=initial_dict)
                else:
                    form = form_cls(initial=request.GET)

                if cancel:
                    cancel_url = request.get_full_path().replace("&edit=True", "") + "&cancel=True"

            fragment = request.GET.get("fragment")

            # cancel-urls (eg on edit) we need the parent object to re-render
            # XXX moderation initial write + cancel, I don't have the moderation object
            if request.GET.get("cancel", None):
                target_object = target_object or _fetch_object_from_class(target_type, target_id)
                rendered = render_to_string(
                    cancel_template,
                    context=dict(
                        fragment=fragment,
                        m=target_object,
                        policy=getattr(request, "policy", None)
                    ),
                    request=request
                )
            else:
                rendered = render_to_string(
                    template,
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


#
# ____    ____  __   ___________    __    ____   _______.
# \   \  /   / |  | |   ____\   \  /  \  /   /  /       |
#  \   \/   /  |  | |  |__   \   \/    \/   /  |   (----`
#   \      /   |  | |   __|   \            /    \   \    
#    \    /    |  | |  |____   \    /\    / .----)   |   
#     \__/     |__| |_______|   \__/  \__/  |_______/    
#
#                                                       

# ------------------------------ About Page ------------------------------------
# XXX Quorum is not global, should be static, then in urls.py
def about(request):
    return render(request, 'static/about.html', context=dict(
        quorums=Quorum.objects.order_by("-created_at"))
                  )


# ---------------------------- Language Page -----------------------------------
# XXX do directly in urls.py
def account_language(request):
    return render(request, "account/language.html")


# ---------------------------- Crawler -----------------------------------
# XXX ?
def crawler(request, filename):
    return render(request, filename, {}, content_type="text/plain")


# ----------------------------- Policy Item ------------------------------------
@policy_state_access()
def policy_item(request, policy, *args, **kwargs):
  if not request.guard.policy_view(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("home")

  payload = _generate_payload(policy)
  payload["is_commentable"] = settings.USE_ARGUMENT_COMMENTS == 1
  payload["is_likeable"] = request.guard.is_likeable(policy)
  payload.update({"policy_labels": dict([(key, settings.PLATFORM_POLICY_FIELD_LABELS[key]) for key in payload["policy_fields"]])})
  payload.update({"is_evaluated": request.guard.is_evaluated(policy=policy)})

  # personalise if authenticated user interacted with policy
  # XXX permission things should be handled in guard.py
  if request.user.is_authenticated:
    user_id = request.user.id
    payload.update({"has_supported": policy.supporting_policy.filter(user=user_id, ack=True).count()})
    payload.update({"has_initiated": policy.supporting_policy.filter(user=user_id, initiator=True).count()})
    vote = policy.policy_votes.filter(user=user_id)
    payload.update({"has_voted": vote.count()})
    if vote:
      payload.update({"vote": vote[0]})

    for arg in payload["policy_arguments"] + payload["policy_proposals_active"] + payload["policy_proposals_stale"]:
      _personalize_argument(arg, user_id)
    for arg in payload["policy_arguments"]:
      if arg.user.id == user_id:
        payload["has_voiced_his_opinion"] = True
        break

  return render(request, 'initproc/policy_item.html', context=payload)


# ----------------------------- Policy Edit ------------------------------------
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_EDIT_STATE_LIST)
def policy_edit(request, policy, *args, **kwargs):
    if not request.guard.policy_view(policy) or not request.guard.policy_edit(policy):
        messages.warning(request, _("Permission denied."))
        return policy_item(request, policy.id, *args, **kwargs)

    print(type(policy.tags.all()))
    form = PolicyForm(request.POST or None, instance=policy)
#    form.tags.prepare_value(policy.tags)

    if request.method == 'POST':
        user = request.user
        if form.is_valid():

            print(form['tags'].value())

            with reversion.create_revision():
                policy.tags = form['tags'].value()
                policy.save()
                reversion.set_user(user)

            # ask initial supporters to repledge? draft, only author can edit,
            # will not be notified. if staged, initiators will be notified to repledge
            supporters = policy.supporting_policy.filter(initiator=True).exclude(user_id=user.id)
            supporters.update(ack=False)
            notify(
                [supporter.user for _, supporter in enumerate(supporters)],
                settings.NOTIFICATIONS.PUBLIC.POLICY_EDITED, {
                    "description": "".join(
                        [_("Policy edited:"), " ", policy.title, ". ", _("Please reconfirm your support.")])
                }, sender=user
            )
            messages.success(request, _("Policy updated."))
            return redirect("/policy/{}".format(policy.id))
        else:
            messages.warning(request, _("Please correct the following problems:"))

    return render(request, "initproc/policy_edit.html", context=dict(form=form, policy=policy, form_media=form.media))


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

            Supporter(
                policy=policy_object,
                user=user,
                first=True,
                initiator=True,
                ack=True,
                public=True
            ).save()

            messages.success(request, _("Created new Policy draft."))
            return redirect('/policy/{}-{}'.format(policy_object.id, policy_object.slug))
        else:
            messages.warning(request, _("Please fill out all required fields."))

    return render(request, 'initproc/policy_edit.html', context=dict(form=form))


# ------------------------- Policy Moderation Show -----------------------------
# toggle evaluation feedback
@ajax
@login_required
@policy_state_access()
def policy_stale_feedback(request, policy, *args, **kwargs):
    user = request.user

    fake_context = dict(
        policy=policy,
        stale=1 if request.GET.get('toggle', None) else 0,
    )

    if user:
        user_id = request.user.id
        fake_context["moderations"] = policy.policy_moderations.filter(stale=True)

    return {
        "fragments": {
            "#moderation-old": render_to_string(
                "fragments/moderation/moderation_list.html",
                context=fake_context,
                request=request,
            )
        }
    }


# ------------------------- Policy Proposals Show ------------------------------
# toggle proposal content and comments
@ajax
@login_required
@policy_state_access()
def policy_stale_proposals(request, policy, *args, **kwargs):
    user = request.user

    fake_context = dict(
        policy=policy,
        stale=1 if request.GET.get('toggle', None) else 0,
    )

    if user:
        user_id = request.user.id
        proposals = policy.policy_proposals.prefetch_related("likes").all()
        fake_context["policy_proposals_stale"] = [x for x in proposals.filter(stale=True)]
        fake_context["policy_proposals_stale"].sort(key=lambda x: (-x.likes.count(), x.created_at))

    return {
        "fragments": {
            "#proposals-old": render_to_string(
                "fragments/discussion/discussion_proposal_list.html",
                context=fake_context,
                request=request,
            )
        }
    }


# ------------------------- Policy Validation Show -----------------------------
# toggle evaluation feedback
@ajax
@login_required
@policy_state_access()
def policy_feedback(request, policy, *args, **kwargs):
    user = request.user
    moderation = get_object_or_404(Moderation, pk=kwargs["target_id"])

    # XXX Duplicate

    # toggle the comment thread
    fake_context = dict(
        m=moderation,
        policy=policy,
        has_commented=False,
        has_blockers=False,
        is_likeable=request.guard.is_likeable(policy) and not moderation.stale,
        full=1 if request.GET.get('toggle', None) is None else 0,
        comments=moderation.comments.order_by('created_at').all()
    )

    if user:

        # XXX fix this, don't set to empty string
        if moderation.blockers:
            fake_context["has_blockers"] = True
            fake_context["blockers"] = []

            for blocker in moderation.blockers.split(","):
                fake_context["blockers"].append(settings.PLATFORM_MODERATION_FIELD_LABELS[blocker])

        for comment in fake_context["comments"]:
            if comment.created_at > user.last_login:
                comment.is_unread = True
            if user.id != comment.user.id:
                comment.has_liked = comment.likes.filter(user=user).exists()
            else:
                comment.can_modify = request.guard.is_editable(comment)

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


# ------------------------------ Landing Page ----------------------------------
def index(request):
    policies = request.guard.make_policy_query()

    count_inbox = len(policies)
    filters = PolicyFilter(request.GET, queryset=policies)
    has_filters = 'q' in request.GET

    return render(
        request,
        'initproc/index.html',
        context=dict(
            policy_list=policies,
            inbox_count=count_inbox,
            filter=filters
        )
    )


class UserAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated():
            return get_user_model().objects.none()

        qs = get_user_model().objects.filter(is_active=True).all()

        if self.q:
            qs = qs.filter(
                Q(first_name__icontains=self.q) | Q(last_name__icontains=self.q) | Q(username__icontains=self.q))

        return qs

    def get_result_label(self, item):
        return render_to_string('fragments/autocomplete/user_item.html',
                                context=dict(user=item))


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
        messages.warning(request, "".join(
            [_("Undo not possible. Please contact the Policy team in case you require assistance. Error:"),
             undo_error]))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))

    with reversion.create_revision():
        policy.state = undo_state
        policy.save()

        reversion.set_user(request.user)
        messages.success(request, _("Reverted to previous state."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))


# ---------------------- Policy Apply (as Co-Initiator) ------------------------
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_INVITE_STATE_LIST)
def policy_apply(request, policy, *args, **kwargs):
    if not request.guard.policy_apply(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))

    # careful, if applicant may already be supporter
    user = request.user
    try:
        supporting_supporter = policy.supporting_policy.get(user_id=user.id)
    except Supporter.DoesNotExist:
        supporting_supporter = Supporter(user=user, policy=policy, ack=False)

    supporting_supporter.initiator = True
    supporting_supporter.first = False
    supporting_supporter.ack = False

    # we hijack this field to distinguish between invitiation and application
    supporting_supporter.public = False
    supporting_supporter.save()

    messages.success(request, _("You have applied as Co-Initiator for this Policy. Please wait for approval."))
    return redirect('/policy/{}'.format(policy.id))


# ---------------------------- Policy Invite -----------------------------------
@ajax
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_INVITE_STATE_LIST)
@simple_form_verifier(InviteUsersForm, submit_title=_("Invite"))
def policy_invite(request, form, policy, invite_type, *args, **kwargs):
    # skip ourselves, nothing to do if sufficient amount of co-initiators reached
    for user in form.cleaned_data["user"]:
        if user == request.user:
            continue

        try:
            supporting_supporter = policy.supporting_policy.get(user_id=user.id)
        except Supporter.DoesNotExist:
            supporting_supporter = Supporter(user=user, policy=policy, ack=False)

        if invite_type == "initiators":
            supporting_supporter.initiator = True
            supporting_supporter.first = False
            supporting_supporter.ack = False
        elif invite_type == "supporters":
            supporting_supporter.first = True
            supporting_supporter.ack = False

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
def policy_acknowledge_support(request, policy, user_id, *args, **kwargs):
    user = request.user
    ack_supporter = get_object_or_404(Supporter, policy=policy, user_id=user_id)
    ack_supporter.ack = True
    ack_supporter.public = True
    ack_supporter.save()

    # only inform if co-initiator signed on and founder isn't operating himself
    if ack_supporter.initiator == True and user_id == request.user.id:
        notify(
            [supporter.user for _, supporter in
             enumerate(policy.supporting_policy.filter(initiator=True).exclude(id=user_id))],
            settings.NOTIFICATIONS.PUBLIC.POLICY_SUPPORT_ACCEPTED,
            {"description": "".join(
                [user.first_name, " ", user.last_name, _(" confirmed to be co-initiator on policy: "), policy.title])},
            sender=user
        )

    messages.success(request, _("Thank you for the confirmation."))
    return redirect("/policy/{}".format(policy.id))


# ---------------------------- Policy Remove Support ---------------------------
@require_POST
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_EDIT_STATE_LIST)
def policy_remove_support(request, policy, user_id, *args, **kwargs):
    user = request.user
    rm_supporter = get_object_or_404(Supporter, policy=policy, user_id=user_id)

    if rm_supporter.initiator == True and user_id == request.user.id:
        notify(
            [supporter.user for _, supporter in
             enumerate(policy.supporting_policy.filter(initiator=True).exclude(id=user_id))],
            settings.NOTIFICATIONS.PUBLIC.POLICY_SUPPORT_REJECTED,
            {"description": "".join(
                [user.first_name, " ", user.last_name, _(" resigned as co-initiator of policy: "), policy.title])},
            sender=user
        )

    rm_supporter.delete()

    # redirect to home handled by policy_item if applicable
    messages.success(request, _("Support has been removed."))
    return redirect("/policy/{}".format(policy.id))


# ---------------------------- Policy Stage ------------------------------------
@login_required
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.DRAFT, settings.PLATFORM_POLICY_STATE_DICT.REJECTED])
def policy_stage(request, policy, *args, **kwargs):
    if not request.guard.policy_edit(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("home")

    if policy.was_challenged_at:
        policy.was_reopened_at = datetime.now()

    policy.state = settings.PLATFORM_POLICY_STATE_DICT.STAGED
    policy.was_staged_at = datetime.now()
    policy.save()

    messages.success(request, _(
        "Policy moved to public status 'Staged'. It is now possible to invite co-initiators and supporters."))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))


# ----------------------------- Policy Delete ----------------------------------
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
@policy_state_access(
    states=[settings.PLATFORM_POLICY_STATE_DICT.INVALIDATED, settings.PLATFORM_POLICY_STATE_DICT.STAGED])
def policy_submit(request, policy, *args, **kwargs):
    if not request.guard.policy_submit(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))

    user = request.user
    tokeniser = UndoUrlTokenGenerator()
    revert_url = "/policy/{}-{}/undo/{}".format(policy.id, policy.slug, tokeniser.create_token(user, policy))
    revert_message = "Policy submitted. Policy submitted for moderation. You will receive a message once feedback on the Policy is availble. <a href='%s'>%s</a>." % (
    revert_url, _("Click here to UNDO."))

    if policy.state == settings.PLATFORM_POLICY_STATE_DICT.STAGED:
        policy.state = settings.PLATFORM_POLICY_STATE_DICT.SUBMITTED
    policy.save()

    # remove unconfirmed supporters
    policy.supporting_policy.filter(initiator=True, ack=False).delete()

    # XXX how to handle UNDO?
    # notifiy initiators
    supporters = policy.supporting_policy.filter(initiator=True).exclude(user_id=user.id)
    notify(
        [supporter.user for _, supporter in enumerate(supporters)],
        settings.NOTIFICATIONS.PUBLIC.POLICY_SUBMITTED, {
            "description": "".join([_("Policy submitted:"), " ", policy.title, ". ", _("Awaiting moderation.")])
        }, sender=user
    )

    # notify policy team with moderation permission
    notify(
        [moderation.user for moderation in policy.policy_moderations.all()],
        settings.NOTIFICATIONS.PUBLIC.POLICY_SUBMITTED, {
            "description": "".join([_("Policy submitted for moderation:"), " ", policy.title, ". "])
        }, sender=user
    )

    messages.success(request, mark_safe(revert_message))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))


# --------------------------- Policy Challenge ---------------------------------
# rejected policies can be challenged once, adding two more moderations to get
# in case initiators are not ok with initial rejection.
@login_required
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.REJECTED])
def policy_challenge(request, policy, *args, **kwargs):
    if not request.guard.policy_challenge(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))

    if policy.was_challenged_at:
        messages.warning(request, _("Permission denied. Policy has already been challenged."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))

    with reversion.create_revision():
        user = request.user
        policy.state = settings.PLATFORM_POLICY_STATE_DICT.CHALLENGED
        policy.was_challenged_at = datetime.now()
        policy.save()

        reversion.set_user(user)
        supporters = policy.supporting_policy.filter(initiator=True).exclude(id=user.id)

        notify(
            [supporter.user for _, supporter in enumerate(supporters)],
            settings.NOTIFICATIONS.PUBLIC.POLICY_CHALLENGED, {
                "description": "".join([_("Rejected Policy challenged:"), " ", policy.title, ". "])
            }, sender=user
        )

        notify(
            [moderation.user for moderation in policy.policy_moderations.all()],
            settings.NOTIFICATIONS.PUBLIC.POLICY_CHALLENGED, {
                "description": "".join([_("Rejected Policy challenged:"), " ", policy.title, ". "])
            }, sender=user
        )

        return redirect("/policy/{}-{}".format(policy.id, policy.slug))


# ---------------------------- Policy Reject -----------------------------------
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_MODERATION_STATE_LIST)
def policy_reject(request, policy, *args, **kwargs):
    if not request.guard.policy_validate(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))

    # rejection does not need ready-for-next-stage (fields filled, initiators),
    # ready-to-proceed will check if Yes > No
    if not policy.ready_to_proceed:
        user = request.user

        policy.policy_moderations.update(stale=True)
        policy.was_rejected_at = datetime.now()
        policy.state = settings.PLATFORM_POLICY_STATE_DICT.REJECTED
        policy.save()

        # we can inform all supporters, because there is only initiators
        supporters = policy.supporting_policy.filter(initiator=True).exclude(id=user.id)
        notify(
            [supporter.user for _, supporter in enumerate(supporters)],
            settings.NOTIFICATIONS.PUBLIC.POLICY_REJECTED, {
                "description": "".join([_("Policy rejected:"), " ", policy.title, ". "])
            }, sender=user
        )

        notify(
            [moderation.user for moderation in policy.policy_moderations.all()],
            settings.NOTIFICATIONS.PUBLIC.POLICY_REJECTED, {
                "description": "".join([_("Policy rejected:"), " ", policy.title, ". "])
            }, sender=user
        )

        messages.success(request, "".join([
            _(
                "Policy rejected. Aside from a one-time option to challenge by initiators this policy is now frozen for: "),
            settings.PLATFORM_POLICY_RELAUNCH_MORATORIUM_DAYS,
            _("days")
        ]))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))


# ---------------------------- Policy Close ------------------------------------
@login_required
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.VALIDATED])
def policy_close(request, policy, *args, **kwargs):
    if not request.guard.policy_close(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))

    with reversion.create_revision():
        user = request.user

        policy.state = settings.PLATFORM_POLICY_STATE_DICT.CLOSED
        policy.save()

        reversion.set_user(request.user)

        # we can inform all supporters, because there is only initiators
        supporters = policy.supporting_policy.filter(initiator=True).exclude(id=user.id)
        notify(
            [supporter.user for _, supporter in enumerate(supporters)],
            settings.NOTIFICATIONS.PUBLIC.POLICY_CLOSED, {
                "description": "".join([_("Policy was closed:"), " ", policy.title, ". "])
            }, sender=user
        )

        notify(
            [moderation.user for moderation in policy.policy_moderations.all()],
            settings.NOTIFICATIONS.PUBLIC.POLICY_CLOSED, {
                "description": "".join([_("Policy was closed:"), " ", policy.title, ". "])
            }, sender=user
        )

        messages.success(request, _("Policy validated. It can now seek supporters and be discussed."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))


# ---------------------------- Policy Discuss ----------------------------------
@login_required
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.VALIDATED])
def policy_discuss(request, policy, *args, **kwargs):
    if not request.guard.policy_discuss(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))

    with reversion.create_revision():
        user = request.user

        policy.went_in_discussion_at = datetime.now()
        policy.state = settings.PLATFORM_POLICY_STATE_DICT.DISCUSSED
        policy.save()

        reversion.set_user(request.user)

        # inform all supporters that they can discuss
        supporters = policy.supporting_policy.exclude(id=user.id)
        notify(
            [supporter.user for _, supporter in enumerate(supporters)],
            settings.NOTIFICATIONS.PUBLIC.POLICY_DISCUSSED, {
                "description": "".join([_("Policy:"), " ", policy.title, _(" was moved into dicussion.")])
            }, sender=user
        )

        notify(
            [moderation.user for moderation in policy.policy_moderations.all()],
            settings.NOTIFICATIONS.PUBLIC.POLICY_DISCUSSED, {
                "description": "".join([_("Policy:"), " ", policy.title, _(" was moved into dicussion.")])
            }, sender=user
        )

        messages.success(request, _("Policy moved to discussion. It can now be discussed among all users."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))


# ---------------------------- Policy Review ----------------------------------
@login_required
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.DISCUSSED])
def policy_review(request, policy, *args, **kwargs):
    if not request.guard.policy_review(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))

    user = request.user
    policy.state = settings.PLATFORM_POLICY_STATE_DICT.REVIEWED
    policy.save()

    # notifiy initiators
    supporters = policy.supporting_policy.filter(initiator=True)
    notify(
        [supporter.user for _, supporter in enumerate(supporters)],
        settings.NOTIFICATIONS.PUBLIC.POLICY_REVIEWED, {
            "description": "".join(
                [_("Policy"), " ", policy.title, " ", _("can now be edited for final review and vote.")])
        }, sender=user
    )

    messages.success(request, _("Policy moved to final edit stage. Initiators can now make final modifications."))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))


# ---------------------------- Policy Finalise --------------------------------
@login_required
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.REVIEWED])
def policy_finalise(request, policy, *args, **kwargs):
    if not request.guard.policy_finalise(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))

    user = request.user
    policy.state = settings.PLATFORM_POLICY_STATE_DICT.FINALISED
    policy.save()

    # notifiy existing moderators
    # XXX all moderators?
    notify(
        [moderation.user for moderation in policy.policy_moderations.all()],
        settings.NOTIFICATIONS.PUBLIC.POLICY_FINALISED, {
            "description": "".join([_("Policy:"), " ", policy.title, " was submitted for final review."])
        }, sender=user
    )

    supporters = policy.supporting_policy.filter(initiator=True)
    notify(
        [supporter.user for _, supporter in enumerate(supporters)],
        settings.NOTIFICATIONS.PUBLIC.POLICY_REVIEWED, {
            "description": "".join([_("Policy"), " ", policy.title, " ", _("can be reviewed and put up for vote.")])
        }, sender=user
    )

    messages.success(request, _("Policy submitted for final Review."))
    return redirect("/policy/{}-{}".format(policy.id, policy.slug))


# ---------------------------- Policy Validate ---------------------------------
# this is the step of moving a policy to validation status
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_MODERATION_STATE_LIST)
def policy_validate(request, policy, *args, **kwargs):
    if not request.guard.policy_validate(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("home")

    if policy.ready_for_next_stage:
        with reversion.create_revision():
            user = request.user

            # delete non-confirmed supporters
            policy.supporting_policy.filter(ack=False).delete()

            # reviews are now stale = OLD
            policy.policy_moderations.update(stale=True)
            policy.was_validated_at = datetime.now()
            policy.state = settings.PLATFORM_POLICY_STATE_DICT.VALIDATED
            policy.save()

            reversion.set_user(request.user)

            # we can inform all supporters, because there is only initiators
            supporters = policy.supporting_policy.filter(initiator=True).exclude(id=user.id)
            notify(
                [supporter.user for _, supporter in enumerate(supporters)],
                settings.NOTIFICATIONS.PUBLIC.POLICY_VALIDATED, {
                    "description": "".join([_("Policy validated:"), " ", policy.title, ". "])
                }, sender=user
            )

            notify(
                [moderation.user for moderation in policy.policy_moderations.all()],
                settings.NOTIFICATIONS.PUBLIC.POLICY_VALIDATED, {
                    "description": "".join([_("Policy validated:"), " ", policy.title, ". "])
                }, sender=user
            )

            messages.success(request, _("Policy validated. It can now seek supporters and be discussed."))
            return redirect("/policy/{}-{}".format(policy.id, policy.slug))


# --------------------------- Policy Evaluate ----------------------------------
# used to be for incoming and moderation (submit and release)
# every validation is an evaluation, once the required number of evaluations are 
# in, policy lead can manually validate a proposal into seeking support stage
@ajax
@login_required
@policy_state_access(states=settings.PLATFORM_POLICY_MODERATION_STATE_LIST)
@simple_form_verifier(NewModerationForm, submit_title=_("Save"),
                      cancel=True, cancel_template="fragments/moderation/moderation_item.html")
def policy_evaluate(request, form, policy, *args, **kwargs):
    if not request.guard.policy_evaluate(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))

    if form.is_valid():
        user = request.user

        # always invalidate with every moderation unless we're in finalised
        if not policy.state in [
            settings.PLATFORM_POLICY_STATE_DICT.CHALLENGED,
            settings.PLATFORM_POLICY_STATE_DICT.INVALIDATED,
            settings.PLATFORM_POLICY_STATE_DICT.FINALISED
        ]:
            raise Exception("CHANGING TO INVALITDAWD")
            policy.state = settings.PLATFORM_POLICY_STATE_DICT.INVALIDATED
            policy.save()

        blockers = [field_id for field_id, _ in form.fields.items() if
                    request.POST.get(field_id, False) and field_id.startswith("q")]

        # a user can only moderate a policy once, so user already moderated this
        # policy, it's an edit, new text will be a comment
        moderation = policy.policy_moderations.filter(user=user.id, stale=False)
        if moderation:
            moderation = moderation[0]
            moderation.vote = form.cleaned_data["vote"]
            # moderation.text = form.cleaned_data["text"]
            moderation.blockers = ",".join(blockers) if blockers else None
            moderation.changed_at = datetime.now()
            moderation.save()

            new_comment = Comment(
                target=moderation,
                user=request.user,
                text=form.cleaned_data["text"]
            )
            new_comment.save()
            new_comment.can_modify = True

        else:
            moderation = form.save(commit=False)
            moderation.policy = policy
            moderation.user = user
            moderation.blockers = ",".join(blockers) if blockers else None
            moderation.save()

    messages.success(request, _("Moderation review recorded."))
    return redirect('/policy/{}'.format(policy.id))


# ----------------------------- Policy Support ---------------------------------
# XXX no checks?
@login_required
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.VALIDATED])
def policy_support(request, policy, *args, **kwargs):
    Supporter(
        policy=policy,
        user_id=request.user.id,
        public=not not request.GET.get("public", False),
        ack=True,
    ).save()

    messages.success(request, _("You are supporting this policy."))
    return redirect('/policy/{}'.format(policy.id))


# ----------------------------- Policy Release --------------------------------
@login_required
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.FINALISED])
def policy_release(request, policy, *args, **kwargs):
    if not request.guard.policy_release(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}-{}".format(policy.id, policy.slug))

    policy.went_to_vote_at = datetime.now()
    policy.state = settings.PLATFORM_POLICY_STATE_DICT.VOTED
    policy.save()

    # inform all users a vote is pending
    notify(
        [user for user, _ in enumerate(User.objects.filter(is_active=True))],
        settings.NOTIFICATIONS.PUBLIC.POLICY_RELEASED, {
            "description": "".join([_("Policy has been released for vote:"), " ", policy.title, ". "])
        }, sender=request.user
    )

    # if request.guard.policy_release(policy):
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

    messages.success(request, _("Policy released for vote."))
    return redirect('/policy/{}'.format(policy.id))

# ------------------------- Policy Vote Conclude -------------------------------
@login_required
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.VOTED])
def policy_conclude(request, policy, *args, **kwargs):

  if not request.guard.policy_conclude(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("/policy/{}".format(policy.id))
 
  policy.state = settings.PLATFORM_POLICY_STATE_DICT.CONCLUDED
  policy.save()
  
  messages.success(request, _("Policy vote concluded. Please accept or close the Policy."))
  return redirect('/policy/{}'.format(policy.id))


# ---------------------------- Policy Publish ----------------------------------
@login_required
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.CONCLUDED])
def policy_publish(request, policy, *args, **kwargs):

  if not request.guard.policy_publish(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("/policy/{}".format(policy.id))
 
  user = request.user
  supporters = policy.supporting_policy.filter(initiator=True).exclude(user_id=user.id)
  notify(
    [supporter.user for _, supporter in enumerate(supporters)],
    settings.NOTIFICATIONS.PUBLIC.POLICY_PUBLISHED, {
      "description": "".join([_("Policy published:"), " ", policy.title, ". ", _("Congratulations!")])
    }, sender=user
  )

  policy.state = settings.PLATFORM_POLICY_STATE_DICT.PUBLISHED
  policy.was_published_at = datetime.now()
  policy.save()
  
  messages.success(request, _("The Policy was published successfully."))
  return redirect('/policy/{}'.format(policy.id))


# ----------------------------- Policy Refrain ---------------------------------
# XXX no checks?
@login_required
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.VALIDATED])
def policy_refrain(request, policy, *args, **kwargs):
    policy.supporting_policy.filter(user_id=request.user.id).delete()
    policy.save()

    messages.success(request, _("You are no longer supporting this policy."))
    return redirect('/policy/{}'.format(policy.id))


# ----------------------------- Policy History ---------------------------------
@_non_ajax_redir('/')
@ajax
@policy_state_access()
def policy_history(request, policy, slug, version_id):
    versions = Version.objects.get_for_object(policy)
    latest = versions.first()
    selected = versions.filter(id=version_id).first()
    policy_field_meta = PolicyBase._meta.get_fields()
    policy_fields = [f.name for f in policy_field_meta]
    policy_labels = dict(
        [(key, settings.PLATFORM_POLICY_FIELD_LABELS[key]) for key in policy_fields]
    )

    compare = {key: mark_safe(
        html_diff(
            _get_policy_field_value(key, selected, policy_field_meta),
            _get_policy_field_value(key, latest, policy_field_meta)
        )
    ) for key in policy_fields}

    compare['was_validated_at'] = policy.was_validated_at

    return {
        "inner-fragments": {
            "header": "",
            ".main": render_to_string(
                "fragments/policy/policy_compare.html",
                context=dict(
                    policy=policy,
                    selected=selected,
                    latest=latest,
                    compare=compare,
                    policy_fields=policy_fields,
                    policy_labels=policy_labels
                ),
                request=request
            )
        }
    }


# ------------------------- Policy History Delete ------------------------------
# not sure this is so wise
@_non_ajax_redir('/')
@ajax
@policy_state_access()
def policy_history_delete(request, policy, slug, version_id):
    if not request.guard.policy_history_delete(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}".format(policy.id))

    versions = Version.objects.get_for_object(policy)
    latest = versions.first()
    if latest.id != version_id:
        selected = versions.filter(id=version_id).first().delete()

    return policy_history(request, policy, slug, latest.id)



# ------------------------- Policy Proposal New --------------------------------
@_non_ajax_redir('/')
@ajax
@login_required
@policy_state_access(states=[
    settings.PLATFORM_POLICY_STATE_DICT.DISCUSSED,
    settings.PLATFORM_POLICY_STATE_DICT.STAGED,
])
@simple_form_verifier(NewProposalForm, submit_title=_("Submit"))
def policy_proposal_new(request, form, policy, *args, **kwargs):
    if not request.guard.policy_proposal_new(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}/%23discuss".format(policy.id))

    if form.is_valid():
        user = request.user
        data = form.cleaned_data
        proposal = Proposal(
            policy=policy,
            user_id=user.id,
            title=data['title'],
            text=data['text'],
            stale=False
        )
        proposal.save()

        # inform all supporters proposal was posted
        supporters = policy.supporting_policy.exclude(id=user.id)
        notify(
            [supporter.user for _, supporter in enumerate(supporters)],
            settings.NOTIFICATIONS.PUBLIC.POLICY_PROPOSAL_NEW, {
                "description": "".join([_("New proposal posted in discussion on Policy:"), " ", policy.title])  # ,
                # "argument": arg
            }, sender=user
        )

        return {
            "fragments": {"#no-proposals": ""},
            "inner-fragments": {
                "#proposal-new": render_to_string(
                    "fragments/discussion/policy_propose_new.html",
                    context=dict(policy=policy)
                ),
                "#proposal-thanks": render_to_string(
                    "fragments/discussion/policy_propose_thanks.html"
                ),
                # must be proposals - because tab header is dynamic...
                "#proposals-count": policy.policy_proposals.count()
            },
            "append-fragments": {
                "#proposal-list": render_to_string(
                    "fragments/discussion/discussion_item.html",
                    context=dict(
                        argument=proposal,
                        full=0
                    ),
                    request=request
                )
            }
        }


# ------------------------- Policy Argument New --------------------------------
@_non_ajax_redir('/')
@ajax
@login_required
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.DISCUSSED])
@simple_form_verifier(NewArgumentForm, template="fragments/discussion/policy_argument_new.html")
def policy_argument_new(request, form, policy, *args, **kwargs):
    # if not request.guard.policy_proposal_new(policy):
    # messages.warning(request, _("Permission denied."))
    # return redirect("/policy/{}".format(policy.id))

    if form.is_valid():
        user = request.user
        data = form.cleaned_data
        argumentClass = Pro if data['type'] == "thumbs_up" else Contra

        arg = argumentClass(
            policy=policy,
            user_id=request.user.id,
            title=data['title'],
            text=data['text'])

        arg.save()

        # inform all supporters an argument was posted
        supporters = policy.supporting_policy.exclude(id=user.id)
        notify(
            [supporter.user for _, supporter in enumerate(supporters)],
            settings.NOTIFICATIONS.PUBLIC.POLICY_ARGUMENT_NEW, {
                "description": "".join([_("New argument posted in discussion on Policy:"), " ", policy.title])  # ,
                # "argument": arg
            }, sender=user
        )

        return {
            "inner-fragments": {
                "#argument-new": render_to_string(
                    "fragments/discussion/policy_thumbs.html",
                    context=dict(policy=policy)
                ),
                "#argument-thanks": render_to_string("fragments/discussion/policy_argument_thanks.html"),
                "#arguments-count": policy.policy_pros.count() + policy.policy_contras.count()
            },
            "append-fragments": {
                "#argument-list": render_to_string(
                    "fragments/discussion/discussion_item.html",
                    context=dict(
                        argument=arg,
                        full=0
                    ),
                    request=request
                )
            }
        }


# ----------------------------- Target Comment  ---------------------------------
@_non_ajax_redir('/')
@ajax
@login_required
@simple_form_verifier(NewCommentForm, cancel=True, cancel_template="fragments/comment/comment_add.html")
def target_comment(request, form, target_type, target_id, *args, **kwargs):
    model_class = apps.get_model('initproc', target_type)
    target_object = get_object_or_404(model_class, pk=target_id)

    if not request.guard.target_comment(target_object):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}/".format(request.policy.id))

    data = form.cleaned_data
    new_comment = Comment(target=target_object, user=request.user, **data)
    new_comment.save()
    new_comment.can_modify = True

    # XXX remove html
    return {
        "inner-fragments": {
            "#{}-new-comment".format(target_object.unique_id): "".join(
                ["<div class='voty-thanks'><strong>", _("Thank you for your comment."), "</strong>",
                 _("It is editable during the next 5 minutes</div>")]),
            "#{}-chat-icon".format(target_object.unique_id): "chat_bubble",
            "#{}-comment-count".format(target_object.unique_id): target_object.comments.count()
        },
        "append-fragments": {
            "#{}-comment-list".format(target_object.unique_id): render_to_string(
                "fragments/comment/comment_item.html",
                context=dict(comment=new_comment),
                request=request
            )
        }
    }


# ------------------------------ Target Like -----------------------------------
@_non_ajax_redir('/')
@ajax
@login_required
def target_like(request, target_type, target_id):
    model_class = apps.get_model('initproc', target_type)
    target_object = get_object_or_404(model_class, pk=target_id)
    parent_policy, target_parent = _get_related_policy(target_object)

    if not request.guard.can_like(target_object):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}/".format(parent_policy.id))

    fake_context = {
        "target": target_object,
        "with_link": True,
        "show_text": False,
        "show_count": True,
        "has_liked": True,
        "is_likeable": request.guard.is_likeable(parent_policy)
    }

    for key in ['show_text', 'show_count']:
        if key in request.GET:
            fake_context[key] = _param_as_bool(request.GET[key])

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
@_non_ajax_redir('/')
@ajax
@login_required
def target_unlike(request, target_type, target_id):
    model_class = apps.get_model('initproc', target_type)
    target_object = get_object_or_404(model_class, pk=target_id)
    parent_policy, target_parent = _get_related_policy(target_object)

    if not request.guard.can_like(target_object):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}/".format(parent_policy.id))

    target_object.likes.filter(user_id=request.user.id).delete()

    fake_context = {
        "target": target_object,
        "with_link": True,
        "show_text": False,
        "show_count": True,
        "has_liked": False,
        "is_likeable": request.guard.is_likeable(parent_policy)
    }

    for key in ['show_text', 'show_count']:
        if key in request.GET:
            fake_context[key] = _param_as_bool(request.GET[key])

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
@_non_ajax_redir('/')
@ajax
@login_required
@simple_form_verifier(NewCommentForm, submit_title=_("Save"))
def target_edit(request, form, *args, **kwargs):
    model_class = apps.get_model('initproc', kwargs["target_type"])
    target_object = get_object_or_404(model_class, pk=kwargs["target_id"])
    parent_policy, target_parent = _get_related_policy(target_object)

    if not request.guard.is_editable(target_object):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}/".format(parent_policy.id))

    data = form.cleaned_data
    target_object.text = form.cleaned_data["text"]
    target_object.save()
    user = request.user

    # XXX fix: also add to request, guard throws over missing policy on edit
    request.policy = parent_policy

    # XXX target[action] should use a single identifier, not m or argument
    fake_context = dict(
        m=target_parent,
        argument=target_parent,
        policy=parent_policy,
        has_commented=False,
        has_blockers=False,
        is_likeable=request.guard.is_likeable(parent_policy),
        full=1,
        comments=target_parent.comments.order_by('created_at').all()
    )

    if user:
        if getattr(target_parent, "blockers", None) is not None:
            fake_context["has_blockers"] = True
            fake_context["blockers"] = []
            for blocker in target_parent.blockers.split(","):
                fake_context["blockers"].append(settings.PLATFORM_MODERATION_FIELD_LABELS[blocker])

        for comment in fake_context["comments"]:
            if comment.created_at > user.last_login:
                comment.is_unread = True
            if user.id != comment.user.id:
                comment.has_liked = comment.likes.filter(user=user).exists()
            else:
                comment.can_modify = request.guard.is_editable(comment)

        # don't allow two-in-a-row
        if not request.guard.target_comment(target_parent):
            fake_context["has_commented"] = True

    if target_parent.type == "moderation":
        template_url = "fragments/moderation/moderation_item.html"
    else:
        template_url = "fragments/discussion/discussion_item.html"

    return {
        "fragments": {
            "#policy-{moderation.type}-{moderation.id}".format(moderation=target_parent): render_to_string(
                template_url,
                context=fake_context,
                request=request,
            )
        }
    }


# ----------------------------- Target Delete ----------------------------------
@_non_ajax_redir('/')
@ajax
@login_required
def target_delete(request, target_type, target_id):
    model_class = apps.get_model("initproc", target_type)
    target_object = get_object_or_404(model_class, pk=target_id)
    parent_policy, target_parent = _get_related_policy(target_object)

    if not request.guard.is_editable(target_object):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}/".format(parent_policy.id))

    user = request.user
    target_object.delete()

    # XXX everything that uses target[action] should use a single identifier, not
    # m or argument
    fake_context = dict(
        m=target_parent,
        argument=target_parent,
        policy=parent_policy,
        has_commented=False,
        has_blockers=False,
        is_likeable=request.guard.is_likeable(parent_policy),
        full=1,
        comments=target_parent.comments.order_by('created_at').all()
    )

    # XXX fix: also add to request, guard throws over missing policy on edit
    request.policy = parent_policy

    if user:

        if getattr(target_parent, "blockers", None) is not None:
            fake_context["has_blockers"] = True
            fake_context["blockers"] = []
            for blocker in target_parent.blockers.split(","):
                fake_context["blockers"].append(settings.PLATFORM_MODERATION_FIELD_LABELS[blocker])

        for comment in fake_context["comments"]:
            if comment.created_at > user.last_login:
                comment.is_unread = True
            if user.id != comment.user.id:
                comment.has_liked = comment.likes.filter(user=user).exists()
            else:
                comment.can_modify = request.guard.is_editable(comment)

        # don't allow two-in-a-row
        if not request.guard.target_comment(target_parent):
            fake_context["has_commented"] = True

    if target_parent.type == "moderation":
        template_url = "fragments/moderation/moderation_item.html"
    else:
        template_url = "fragments/discussion/discussion_item.html"

    return {
        "fragments": {
            "#policy-{moderation.type}-{moderation.id}".format(moderation=target_parent): render_to_string(
                template_url,
                context=fake_context,
                request=request,
            )
        }
    }


# ------------------------ Policy Argument Solve -------------------------------
@ajax
@login_required
@policy_state_access(states=[
    settings.PLATFORM_POLICY_STATE_DICT.DISCUSSED,
    settings.PLATFORM_POLICY_STATE_DICT.STAGED,
    settings.PLATFORM_POLICY_STATE_DICT.REVIEWED,
])
def policy_argument_solve(request, policy, *args, **kwargs):
    model_class = apps.get_model('initproc', kwargs["target_type"])
    target_object = get_object_or_404(model_class, pk=kwargs["target_id"])
    target_comments = target_object.comments.order_by('created_at').all()

    user = request.user
    set_stale_to = request.GET.get('stale')

    if not request.guard.policy_proposal_solve(policy):
        messages.warning(request, _("Permission denied."))
        return redirect("/policy/{}/%23discuss".format(policy.id))

    # user must have last comment to reopen
    # XXX improve (lost half an hour here on "False" vs False...)
    if set_stale_to == "False" and request.guard.target_comment(target_object):
        payload = _generate_payload(policy)
        payload["voty_error_message"] = _("Please comment on the issue before reopening")
        payload["stale"] = 1
        return {
            "fragments": {
                "#voty-error": render_to_string(
                    "error.html",
                    context=payload,
                    request=request
                ),
                "#proposals-old": render_to_string(
                    "fragments/discussion/discussion_proposal_list.html",
                    context=payload,
                    request=request,
                )
            }
        }

    target_object.stale = set_stale_to
    target_object.save()
    _personalize_argument(target_object, user.id)

    payload = _generate_payload(policy)
    payload["argument"] = target_object
    payload["has_liked"] = target_object.has_liked
    payload["comments"] = target_comments

    # XXX do we really need this?
    payload["has_solved"] = True

    return {
        "fragments": {
            "#discuss": render_to_string(
                "fragments/discussion/discussion_index.html",
                context=payload,
                request=request
            ).join(['<div id="discuss" class="container-fluid cta">', '</div>'])
        }
    }


# ------------------------ Policy Argument Toggle -----------------------------
@ajax
# @login_required
@policy_state_access(states=[
  settings.PLATFORM_POLICY_STATE_DICT.DISCUSSED,
  settings.PLATFORM_POLICY_STATE_DICT.STAGED,
  settings.PLATFORM_POLICY_STATE_DICT.REVIEWED,
] + settings.PLATFORM_POLICY_STALE_DISCUSSION_LIST)
def policy_argument_details(request, policy, *args, **kwargs):
    model_class = apps.get_model('initproc', kwargs["target_type"])
    target_object = get_object_or_404(model_class, pk=kwargs["target_id"])
    user = request.user
    _personalize_argument(target_object, user.id)

    # toggle the comment thread
    fake_context = dict(
        argument=target_object,
        policy=policy,
        has_commented=False,
        has_liked=target_object.has_liked,
        is_likeable=request.guard.is_likeable(policy),
        stale=getattr(target_object, "stale", None),
        full=1 if request.GET.get('toggle', None) is None else 0,
        comments=target_object.comments.order_by('created_at').all()
    )

    if user.is_authenticated:
        for comment in fake_context["comments"]:
            if comment.created_at > user.last_login:
                comment.is_unread = True
            if user.id != comment.user.id:
                comment.has_liked = comment.likes.filter(user=user).exists()
            else:
                comment.can_modify = request.guard.is_editable(comment)

        # don't allow two-in-a-row
        if not request.guard.target_comment(target_object):
            fake_context["has_commented"] = True

    return {
        "fragments": {
            "#policy-{target.type}-{target.id}".format(target=target_object): render_to_string(
                "fragments/discussion/discussion_item.html",
                context=fake_context,
                request=request,
            )
        }
    }


# ------------------------------ Policy Vote ----------------------------------
@_non_ajax_redir('/')
@ajax
@login_required
@require_POST
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.VOTED])
def policy_vote(request, policy, *args, **kwargs):

  if not request.guard.policy_vote(policy):
    messages.warning(request, _("Permission denied."))
    return redirect("/policy/{}".format(policy.id))
    
  voted_value = request.POST.get('voted')
  if voted_value == "no":
    voted = settings.VOTED.NO #0
  elif voted_value == "yes":
    voted = settings.VOTED.YES #1
  else:
    voted = settings.VOTED.ABSTAIN #2

  try:
    user_vote = Vote.objects.get(policy=policy, user_id=request.user)
  except Vote.DoesNotExist:
    user_vote = Vote(policy=policy, user_id=request.user.id, value=voted)
  else:
    user_vote.voted = voted
  user_vote.save()

  fake_context = dict(
    vote=user_vote,
    has_voted=1,
    policy=policy,
    user_count=policy.eligible_voter_count
  )
  
  return {
    "fragments": {},
    "inner-fragments": {
      "#voting": render_to_string(
        "fragments/vote/vote_item.html",
         context=fake_context,
         request=request
       ),
      "#jump-to-vote": render_to_string(
        "fragments/vote/vote_jump.html",
        context=fake_context
      )
    }
  }

# ------------------------------ Policy Vote Reset ---------------------------
@_non_ajax_redir('/')
@ajax
@login_required
@require_POST
@policy_state_access(states=[settings.PLATFORM_POLICY_STATE_DICT.VOTED])
def policy_vote_reset(request, policy, *args, **kwargs):
  Vote.objects.filter(policy=policy, user_id=request.user).delete()
  fake_context = dict(
    policy=policy,
    user_count=policy.eligible_voter_count
  )
  
  return {
    "fragments": {},
    "inner-fragments": {
      "#voting": render_to_string(
        "fragments/vote/vote_item.html",
         context=fake_context,
         request=request
       ),
      "#jump-to-vote": render_to_string(
        "fragments/vote/vote_jump.html",
        context=fake_context
      )
    }
  }
