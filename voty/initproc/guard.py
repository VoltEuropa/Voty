# -*- coding: utf-8 -*-
# ==============================================================================
# voty initproc guard - single one place, where all permissions are defined
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

from django.core.exceptions import PermissionDenied
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.apps import apps
from django.utils.functional import cached_property

from functools import wraps
from voty.initadmin.models import UserConfig
from voty.initproc.models import Moderation
from .globals import STATES, PUBLIC_STATES, TEAM_ONLY_STATES, INITIATORS_COUNT
from .models import Policy, Supporter, Comment
from django.conf import settings
from django.utils import six
from django.utils.translation import ugettext as _
from datetime import datetime, timedelta, timezone

# ================================= HELPERS ====================================
# --------------------------- find parent policy -------------------------------
def _find_parent_policy(self, obj=None):
  while not hasattr(obj, "policy") and hasattr(obj, "target"):
    obj = obj.target
  return obj.policy if hasattr(obj, "policy") else obj

# ================================= CLASSES ====================================   
# ---------------------------- continue checking -------------------------------
class ContinueChecking(Exception):
  pass

# ---------------- Instance of the Guard for the given user --------------------
class Guard:

  def __init__(self, user, request=None):
    self.user = user
    self.request = request

    # XXX REASON IS NOT THREAD SAFE, but works good enough for us for now.
    self.reason = None

  # --------------------- missing moderation reviews to continue -----------------
  def _missing_moderation_evaluations(self, policy):
  
    # total moderators required are based on percentage/minimum person and state
    total = policy.required_moderations
    config = settings.PLATFORM_MODERATION_SETTING_LIST
    moderations = policy.policy_moderations.exclude(vote="r")

    if policy.state == settings.PLATFORM_POLICY_STATE_DICT.FINALISED:
      moderations = moderations.filter(stale=False)
    if policy.was_reopened_at:
      relevant_count = len([x for x in moderations if x.changed_at > policy.was_reopened_at])
    else:
      relevant_count = moderations.count()

    total = total - relevant_count

    # moderator diversity is optional
    if bool(int(settings.USE_DIVERSE_MODERATION_TEAM)):
      female  = round(int(config.MINIMUM_FEMALE_MODERATOR_PERCENTAGE)/100 * total)
      diverse = round(int(config.MINIMUM_DIVERSE_MODERATOR_PERCENTAGE)/100 * total)
  
      # exclude moderator from required quotas if he/she is initiator
      for user_config in UserConfig.objects.filter(user_id__in=moderations.values("user_id")):
        if user_config.is_female_mod:
          female -= 1
        if user_config.is_diverse_mod:
          diverse -= 1
      return (female, diverse, total)
  
    # by default only check for total
    return (0, 0, total)

  # ------------------------------- make policy query ----------------------------
  # XXX keep until landing page is done
  def make_policy_query(self):
    return Policy.objects.all() #for now, just return all

  # XXX this should be calculated elsewhere?
  # @cached_property
  # def minimum_moderation_reviews(self):
  #  return self._get_policy_minium_moderator_votes()

  # ------------------------------ can like ------------------------------------
  def can_like(self, obj=None):
    user = self.user
    if not user.is_authenticated:
      return False
    if obj.user == user:
      return False
    return True

  # ------------------------------ can view ------------------------------------
  def can_view(self, obj=None):
    user = self.user

    if not user.is_authenticated:
      return False
    return True

  # ---------------------- can be undemocratic ---------------------------------
  # XXX we shouldn't
  def can_be_undemocratic(self, policy=None):
    user = self.user

    if user.has_perm("initproc.policy_can_override") or user.is_superuser:
      return True
    return False

  # -------------------------- policy is voted ---------------------------------
  def is_voted(self, policy):
    return policy.policy_votes.filter(user=self.user.id).first()

  # ------------------------ policy is supporting ------------------------------
  def is_supporting(self, policy):
    return policy.supporting_policy.filter(user_id=self.user.id)

  # -----------------------comment is likeable ---------------------------------
  def is_likeable(self, policy=None):
    if policy and policy.state in settings.PLATFORM_POLICY_STALE_STATE_LIST:
      return False
    return True

  # ---------------------- comment is_editable ---------------------------------
  def is_editable(self, obj=None):
    user = self.user

    # this covers edit and delete, moderators should have an option to delete
    # all comments but for now this is not implemented.
    # XXX do this when flags are done. Then a moderator has to flag a comment
    # then it should be deleteable
    if user.is_superuser: #or user.has_perm("initproc.policy_can_review"):
      return True
    if not isinstance (obj, Comment):
      return False
    if obj.user.id != user.id:
      return False
    if datetime.now(timezone.utc) - obj.changed_at > timedelta(seconds=int(settings.PLATFORM_POLICY_COMMENT_EDIT_SECONDS)):
      return False
    return True

  # ---------------------------- edit inivite ----------------------------------
  def invite_edit(self, policy=None):
    policy = policy or self.request.policy
    if policy.supporting_policy.filter(first=True,initiator=True,user_id=self.user.id):
      return True
    return False

  # ---------------------------- view policy -----------------------------------
  def policy_view(self, policy=None):
    policy = policy or self.request.policy
    user = self.user
    
    if policy.state in settings.PLATFORM_POLICY_ADMIN_STATE_LIST:
      if user.has_perm("initproc.policy_can_review") or user.is_superuser:
        return True
      if policy.supporting_policy.filter(initiator=True, user=user.id):
        return True
      return False

    if policy.state == settings.PLATFORM_POLICY_STATE_DICT.DRAFT and \
      not policy.supporting_policy.filter(first=True, user_id=user.id):
      return False

    return True

  # ----------------------------- vote on policy -------------------------------
  def policy_vote(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    #if policy.policy_votes.filter(user=user.id).count():
    #  return False
    return True

  # ----------------- invite co-initiators/supporters to policy ----------------
  def policy_invite(self, policy=None):
    policy = policy or self.request.policy
    user = self.user
    initiators = policy.supporting_policy.filter(initiator=True)

    if not self.policy_edit(policy) and not user.is_superuser:
      return False
    if not initiators.filter(user=user.id):
      return False
    if not policy.state in settings.PLATFORM_POLICY_INVITE_STATE_LIST:
      return False
    return initiators.count() < int(settings.PLATFORM_POLICY_INITIATORS_COUNT)

  # ------------------------ apply as initiator on policy ----------------------
  def policy_apply(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if not policy.state in settings.PLATFORM_POLICY_INVITE_STATE_LIST:
      return False
    if policy.supporting_policy.filter(initiator=True, user_id=user.id):
      return False
    if policy.ready_for_next_stage:
      return False
    return True

  # ---------------------------- edit policy -----------------------------------
  def policy_edit(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if not policy.state in settings.PLATFORM_POLICY_EDIT_STATE_LIST:
      return False
    if not policy.supporting_policy.filter(initiator=True, ack=True, user_id=user.id):
      return False

    # yes/no evaluations < required evaluations = edit while evals are pending
    if not policy.policy_moderations.filter(stale=False).exclude(vote="r").count() < policy.required_moderations:
      if policy.ready_for_next_stage:
        return False

    return True

  # ----------------------- delete policy history ------------------------------
  def policy_history_delete(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if not policy.supporting_policy.filter(initiator=True, ack=True, user_id=user.id):
      return False

    return True


  # ---------------------------- stage policy -----------------------------------
  def policy_stage(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False

    initiators = policy.supporting_policy.filter(initiator=True)
    if policy.state in settings.PLATFORM_POLICY_STATE_DICT.DRAFT:
      if initiators.filter(user=user.id):
        return True
  
    if policy.state in settings.PLATFORM_POLICY_STATE_DICT.REJECTED:
      if policy.ready_for_next_stage and initiators.filter(user=user.id):
        return True
      if user.has_perm("initproc.policy_can_override"):
        return True

    return False

  # ---------------------------- delete policy ---------------------------------
  def policy_delete(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if not policy.state == settings.PLATFORM_POLICY_STATE_DICT.CLOSED:
      return False
    if user.has_perm("initproc.policy_can_delete") or \
      user.is_superuser:
        return True
    return False

  # --------------------------- undelete policy --------------------------------
  def policy_undelete(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if policy.state in settings.PLATFORM_POLICY_STATE_DICT.DELETED and \
      (user.has_perm("initproc.policy_can_delete") or user.is_superuser):
      return True
    return False

  # --------------------------- unhide policy --------------------------------
  def policy_unhide(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if policy.state in settings.PLATFORM_POLICY_STATE_DICT.HIDDEN and \
      (user.has_perm("initproc.policy_can_unhide") or user.is_superuser):
      return True
    return False

  # -------------------------- challenge policy --------------------------------
  def policy_challenge(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if not policy.state ==settings.PLATFORM_POLICY_STATE_DICT.REJECTED:
      return False
    if policy.was_challenged_at:
      self.reason = _("Challenge not possible: Previous challenge failed.")
      return False

    # let rejections be visible nobody else can see why it failed
    #if not initiators.filter(user_id=user.id):
    #  return False
    if not policy.supporting_policy.filter(initiator=True, ack=True).count() >= int(settings.PLATFORM_POLICY_INITIATORS_COUNT):
      self.reason = _("Challenge not possible: Missing confirmed initiators.")
      return False

    # challenge (additional reviews is only possible if it can make a difference
    # required = default eg 3 + challenge eg 2 (will always be uneven!)
    # => if y0:n3 => 5 - 3 > 3, can't challenge
    # => if y1:n2 => 5 - 2 > 2, can challenge
    nos = int(policy.policy_moderations.filter(vote="n").count())
    if policy.required_moderations - nos <= nos:
      self.reason = _("Challenge not possible: additional reviews will not sufficient to overturn Rejection.")
      return False

    return True

  # ---------------------------- submit policy ---------------------------------
  def policy_submit(self, policy=None):
    policy = policy or self.request.policy
    user = self.user
    initiators = policy.supporting_policy.filter(initiator=True, ack=True)

    if not user.is_authenticated:
      return False
    if not initiators.filter(user_id=user.id):
      return False
    if not initiators.count() >= int(settings.PLATFORM_POLICY_INITIATORS_COUNT):
      return False
    if not policy.policy_moderations.filter(stale=False).exclude(vote="r").count() < policy.required_moderations:
      return False
    if not policy.state in [
      settings.PLATFORM_POLICY_STATE_DICT.STAGED,
      # no need to re-submit, it can go back and forth without
      #settings.PLATFORM_POLICY_STATE_DICT.INVALIDATED,
    ]:
      return False
    return True

  # ----------------- solve (open/close policy proposal ------------------------
  def policy_proposal_solve(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if policy.supporting_policy.filter(initiator=True, ack=True).filter(user_id=user.id):
      return True
    return False

  # ---------------------- add proposal to policy ------------------------------
  def policy_proposal_new(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if policy.state == settings.PLATFORM_POLICY_STATE_DICT.STAGED:
      if policy.supporting_policy.filter(initiator=True, ack=True).filter(user_id=user.id):
        return True
    if policy.state == settings.PLATFORM_POLICY_STATE_DICT.DISCUSSED:
      return True
    return False

  # -------------------------- publish policy ----------------------------------
  def policy_publish(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if not policy.state == settings.PLATFORM_POLICY_STATE_DICT.CONCLUDED:
      return False
    if not user.has_perm("initproc.policy_can_publish"):
      return False
    return True
  
  # ---------------------- validate/reject policy ------------------------------
  # checks if user technically CAN validate
  def policy_validate(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    # raise Exception(user.get_all_permissions())
    # only policy leads can validate/reject
    if not policy.state in settings.PLATFORM_POLICY_MODERATION_STATE_LIST:
      return False
    if not user.has_perm("initproc.policy_can_validate"):
      return False
    return True

  # ------------------- evaluate a policy (previous moderation) ----------------
  # checks if user can validate (not whether he/she already has), not whether
  # still missing moderations
  def policy_evaluate(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not policy.state in settings.PLATFORM_POLICY_MODERATION_STATE_LIST:
      return False
    if not user.has_perm("initproc.policy_can_review"):
      return False
    if policy.supporting_policy.filter(user=user.id, initiator=True):
      self.reason = _("Moderation not possible: Initiators cannot moderate own Policy.")
      return False

    # custom criteria
    # XXX make this work eventually (including upping on challenge and review)

    (female, diverse, total) = self._missing_moderation_evaluations(policy)
    try:
      if female > 0:
        if self.user.config.is_female_mod:
          return True
      if diverse > 0:
        if self.user.config.is_diverse_mod:
          return True
    except User.config.RelatedObjectDoesNotExist:
      pass

    return (total >= female) & (total >= diverse)

  # --------------------------- is evaluated ----------------------------------
  # => when to show moderation box to non-moderators
  def is_evaluated(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    # reviews are visible in correct state if you're (logged in?) and initiator
    # if not user.is_authenticated:
    #   return False
    if not policy.state in settings.PLATFORM_POLICY_MODERATION_STATE_LIST:
      return False
    if not policy.supporting_policy.filter(initiator=True, ack=True).filter(user_id=user.id):
      return False

    # show also if no moderations have been made
    #if not policy.policy_moderations.count() > 0:
    #  return False

    return True

  # ------------------------ user has evaluated --------------------------------
  def has_moderated(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not policy.state in settings.PLATFORM_POLICY_MODERATION_STATE_LIST:
      return False

    # in challenged state (previous) moderations also count
    if policy.state == settings.PLATFORM_POLICY_STATE_DICT.CHALLENGED:
      if policy.policy_moderations.filter(user=user.id).count() > 0:
        self.reason = _("You have already reviewed this Policy.")
        return True

    # in all other moderations, only active moderations count
    else:
      if policy.policy_moderations.filter(user=user.id, stale=False).count() > 0:
        self.reason = _("You have already reviewed this Policy.")
        return True
    return False

  # ------------------------ needs evaluations ---------------------------------
  def misses_moderations(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not policy.state in settings.PLATFORM_POLICY_MODERATION_STATE_LIST:
      return False
    if policy.state == settings.PLATFORM_POLICY_STATE_DICT.CHALLENGED:
      if policy.policy_moderations.count() == policy.required_moderations:
        return False
    else:
      if policy.policy_moderations.filter(stale=False).count() == policy.required_moderations:
        return False
    return True

  # --------------------- user can edit evaluation -----------------------------
  def is_reviseable(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    # moderator who reviewed a challenged policy can not evaluate it again
    if policy.state in [
      settings.PLATFORM_POLICY_STATE_DICT.CHALLENGED,
      settings.PLATFORM_POLICY_STATE_DICT.REJECTED
    ]:
      moderations = policy.policy_moderations
    else:
      moderations = policy.policy_moderations.filter(stale=False)

    # already moderated, done
    if moderations.filter(user=self.user).exclude(vote="r"):
      self.reason = _("You have already evaluated this Policy.")
      return False
    return True

  # ---------------------- comment X (anything...) -----------------------------
  def target_comment(self, target_object=None):
    user = self.user

    if not user.is_authenticated:
      return False
  
    policy = _find_parent_policy(target_object)
    self.reason = None
    last_comment = target_object.comments.order_by("-created_at").first()

    # XXX why should moderations have no restrictions toward multiple comments?
    #if (isinstance (target_object, Moderation)):
    #  return True
  
    # can't access policy from here
    if policy and policy.state == settings.PLATFORM_POLICY_STATE_DICT.CHALLENGED:
      self.reason = _("Commenting not possible in challenged state.")
      return False

    if not last_comment and target_object.user == user:
      self.reason = _("Comment not possible: Please wait for another user to comment.")
      return False

    # XXX what's the difference?
    elif last_comment and last_comment.user == user:
      self.reason = _("Comment not possible: Please wait for another user to comment.")
      return False

    return True

  # ------------------------- invalidate policy --------------------------------
  # XXX not sure this is used
  def policy_invalidate(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if policy.state in settings.PLATFORM_POLICY_MODERATION_STATE_LIST:
      if user.has_perm("initproc.policy_can_invalidate") or user.is_superuser:
        if policy.supporting_policy.filter(user=user, initiator=True):
          self.reason = _("Moderation not possible: Initiators can not moderate own Policy")
          return False
        return True
    return False

  # --------------------------- reject policy ----------------------------------
  def policy_reject(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if policy.state in settings.PLATFORM_POLICY_MODERATION_STATE_LIST:
      if user.has_perm("initproc.policy_can_reject"):
        if policy.supporting_policy.filter(user=user, initiator=True):
          self.reason = _("Moderation not possible: Initiators can not moderate own Policy")
          return False
        return True
    return False

  # ---------------------- move policy to discussion ---------------------------
  def policy_discuss(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if not policy.state == settings.PLATFORM_POLICY_STATE_DICT.VALIDATED:
      return False
    if not policy.supporting_policy.filter().count() >= policy.quorum:
      if user.has_perm("initproc.policy_can_override"):
        return True
      return False

    return True

  # --------------------- move policy to final edits ---------------------------
  def policy_review(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if not policy.state == settings.PLATFORM_POLICY_STATE_DICT.DISCUSSED:
      return False
    if not policy.ready_for_next_stage:
      if user.has_perm("initproc.policy_can_override"):
        return True
      return False

    return True

  # ---------------------- move policy to final validation ---------------------
  def policy_finalise(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if not policy.state == settings.PLATFORM_POLICY_STATE_DICT.REVIEWED:
      return False
    if not policy.ready_for_next_stage:
      return False

    return True

  # ------------------------- finish policy (vote) -----------------------------
  def policy_conclude(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if not policy.state == settings.PLATFORM_POLICY_STATE_DICT.VOTED:
      return False
    if not user.has_perm("initproc.policy_can_override"):
      return False
    return True

  # ------------------------ release policy for vote --------------------------
  def policy_release(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if not policy.state == settings.PLATFORM_POLICY_STATE_DICT.FINALISED:
      return False
    if not user.has_perm("initproc.policy_can_override"):
      return False
    return True

  # ---------------------------- close policy ----------------------------------
  def policy_close(self, policy=None):
    policy = policy or self.request.policy
    user = self.user

    if not user.is_authenticated:
      return False
    if not policy.state in [settings.PLATFORM_POLICY_STATE_DICT.VALIDATED]:
      return False
    if policy.supporting_policy.filter().count() >= policy.quorum: 
      return False
    if not user.has_perm("initproc.policy_can_close"):
      return False

    return True

# ----------------------------- Publish Guard ----------------------------------
# Add guard of the request.user and make it accessible directly at request.guard
# This will be called from middleware, see settings.py
def add_guard(get_response):
  def middleware(request):
    guard = Guard(request.user, request)
    request.guard = guard
    request.user.guard = guard

    response = get_response(request)
    return response

  return middleware




