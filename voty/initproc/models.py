# -*- coding: utf-8 -*-
# ==============================================================================
# voty initprocs models
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.utils.functional import cached_property
from django.contrib.auth.models import User, Permission, models
from django.contrib.auth import get_user_model
from django.utils.translation import ugettext as _
from django.db.models import Q
from django.utils.text import slugify
from django.conf import settings
from reversion.models import Version

# initiative
from pinax.notifications.models import send as init_notify

# policy (same as initadmin)
from pinax.notifications.backends.base import BaseBackend
from notifications.signals import notify

from datetime import datetime, timedelta, date
from .globals import STATES, VOTED, INITIATORS_COUNT, SPEED_PHASE_END, ABSTENTION_START
from django.db import models
import reversion
import pytz

# ------------------------ Build Class field dict .-----------------------------
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
    response[field_key] = getattr(models, field_type)(**dict(config_list))

  return response
# ------------------------ Dynamic Class Generator -----------------------------
# allows to create dynamic abstracct classes from settings/ini file, more info,
# see https://code.djangoproject.com/wiki/DynamicModels
# XXX not sure this is the right place?
def _create_model(name, fields=None, app_label="", module="", options=None, admin_options=None):

  # Using type("Meta", ...) gives a dictproxy error during model creation
  class Meta:
    pass

  # app_label must be set using the Meta inner class
  if app_label:
    setattr(Meta, "app_label", app_label)

  # Update Meta with any options that were provided
  if options is not None:
    for key, value in options.items():
      setattr(Meta, key, value)

  # Set up a dictionary to simulate declarations within a class
  attrs = {"__module__": module, "Meta": Meta}

  # Add in any fields that were provided
  if fields:
    attrs.update(fields)

  # Create the class, which automatically triggers ModelBase processing
  model = type(name, (models.Model,), attrs)

  # Create an Admin class if admin options were provided
  if admin_options is not None:
    class Admin(admin.ModelAdmin):
      pass
    for key, value in admin_options:
      setattr(Admin, key, value)
    admin.site.register(model, Admin)

  return model

# ---------------------------- Policy Proxy Class ------------------------------
# this creates an proxy base class which Policy will then inherit from. this 
# allows to define the fields a policy should have in the init.ini file instead
# of hardcoding them here
PolicyBase = _create_model(
  name="PolicyBase",
  fields=_create_class_field_dict(settings.PLATFORM_POLICY_BASE_CONFIG),
  options={
    "abstract": True,

    # https://docs.djangoproject.com/en/1.10/topics/auth/customizing/#custom-permissions
    "permissions": settings.PLATFORM_POLICY_PERMISSION_LIST
  },
  # {} doesn't work with abstract classes contrary to documentation
  admin_options=None,
  app_label="initproc",
)

# ================================== Classes ===================================
# -------------------------------- Policy --------------------------------------
# our new home!
@reversion.register()
class Policy(PolicyBase):

  # fields provided via abstract class from init.ini, now they are configurable

  #summary = models.TextField(blank=True)
  #problem = models.TextField(blank=True)
  #forderung = models.TextField(blank=True)
  #kosten = models.TextField(blank=True)
  #fin_vorschlag = models.TextField(blank=True)
  #arbeitsweise = models.TextField(blank=True)
  #init_argument = models.TextField(blank=True)

  #einordnung = models.CharField(max_length=50, choices=settings.CATEGORIES.CONTEXT_CHOICES)
  #ebene = models.CharField(max_length=100, choices=settings.CATEGORIES.SCOPE_CHOICES)
  #bereich = models.CharField(max_length=60, choices=settings.CATEGORIES.TOPIC_CHOICES)

  # there is so much text stored on an initiative/policy, state can also be
  # human-readable => max-length:20, start in draft
  state = models.CharField(
    max_length=20,
    choices=settings.PLATFORM_POLICY_STATE_LIST,
    default=settings.PLATFORM_POLICY_STATE_DEFAULT
  )

  variant_of = models.ForeignKey('self', blank=True, null=True, default=None, related_name="variants")
  supporters = models.ManyToManyField(User, through="Supporter")
  eligible_voters = models.IntegerField(blank=True, null=True)

  # staged is going from draft (private) to staged (public)
  created_at = models.DateTimeField(auto_now_add=True)
  staged_at = models.DateTimeField(auto_now=True)
  changed_at = models.DateTimeField(auto_now=True)

  # changed published to validated and closed (not used, no?) to published
  was_validated_at = models.DateField(blank=True, null=True)
  went_in_discussion_at = models.DateField(blank=True, null=True)
  went_in_vote_at = models.DateField(blank=True, null=True)
  was_published_at = models.DateField(blank=True, null=True)

  @cached_property
  def slug(self):
    return slugify(self.title)

  @cached_property
  def versions(self):
    return Version.objects.get_for_object(self)

  @cached_property
  def sort_index(self):
    timezone = self.created_at.tzinfo

    # recently published first
    if self.was_published_at:
      return datetime.today().date() - self.was_published_at

    # closest to deadline first
    elif self.end_of_this_phase:
      return self.end_of_this_phase - datetime.today().date()

    # newest first
    else:
      return datetime.now(timezone) - self.staged_at

  @cached_property
  def ready_for_next_stage(self):

    # policy needs minimum initiators and all fields filled
    # all fields required => len>0 = True [True, True, False] = 1*1*0 = 0
    if self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.STAGED,
      settings.PLATFORM_POLICY_STATE_DICT.FINALIZED,
      settings.PLATFORM_POLICY_STATE_DICT.INVALIDATED,
      settings.PLATFORM_POLICY_STATE_DICT.CHALLENGED,
      settings.PLATFORM_POLICY_STATE_DICT.AMENDED,
      settings.PLATFORM_POLICY_STATE_DICT.IN_REVIEW
    ]:
      return (
        self.supporting.filter(initiator=True, ack=True).count() == settings.PLATFORM_POLICY_INITIATORS_COUNT and
        reduce(lambda x, y: x*y, [len(self[f.name]) > 0 for f in PolicyBase._meta.get_fields()])
      )

    if self.state in [settings.PLATFORM_POLICY_STATE_DICT.SUBMITTED]:
      return self.supporting.filter(initiator=True, ack=True).count() == settings.PLATFORM_POLICY_INITIATORS_COUNT

    # note, the Quorum will be specific to each policy
    if self.state == settings.PLATFORM_POLICY_STATE_DICT.VALIDATED:
      return self.supporting.filter().count() >= self.quorum

    # nothing to do
    if self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.DRAFT,
      settings.PLATFORM_POLICY_STATE_DICT.SUPPORTED,
      settings.PLATFORM_POLICY_STATE_DICT.IN_DISCUSSION,
      settings.PLATFORM_POLICY_STATE_DICT.IN_VOTE,
    ]:
      return True

    return False

  @cached_property
  def end_of_this_phase(self):
    week = timedelta(days=7)

    # a closed (rejected) policy can only be re-opened after 
    if self.was_closed_at:
      return self.was_closed_at + timedelta(days=settings.PLATFORM_POLICY_RELAUNCH_MORATORIUM_DAYS)

    if self.was_validated_at:
      if self.state == Initiative.STATES.SEEKING_SUPPORT:
        if self.variant_of:
          if self.variant_of.went_in_discussion_at:
            return self.variant_of.went_in_discussion_at +(2 * week)

        # once support is won, there is an additional waiting phase
        if self.ready_for_next_stage:
          return self.was_validated_at + (2 * week)

      elif self.state == settings.PLATFORM_POLICY_STATE_DICT.IN_DISCUSSION:
        return self.went_in_discussion_at + (3 * week)

      elif self.state == settings.PLATFORM_POLICY_STATE_DICT.IN_REVIEW:
        return self.went_in_discussion_at + (5 * week)

      elif self.state == settings.PLATFORM_POLICY_STATE_DICT.IN_VOTE:
        return self.went_in_vote_at + (3 * week)

    return None

  @cached_property
  def quorum(self):
    return Quorum.current_quorum()

  @property
  def show_supporters(self):
    return self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.STAGED,
      settings.PLATFORM_POLICY_STATE_DICT.SUBMITTED,
      settings.PLATFORM_POLICY_STATE_DICT.VALIDATED
    ]

  @property
  def show_debate(self):
    return self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.IN_DISCUSSION,
      settings.PLATFORM_POLICY_STATE_DICT.IN_REVIEW,
      settings.PLATFORM_POLICY_STATE_DICT.CHALLENGED,
      settings.PLATFORM_POLICY_STATE_DICT.IN_VOTE,
      settings.PLATFORM_POLICY_STATE_DICT.ACCEPTED,
      settings.PLATFORM_POLICY_STATE_DICT.REJECTED,
      settings.PLATFORM_POLICY_STATE_DICT.PUBLISHED
    ]

  @cached_property
  def yays(self):
    return self.votes.filter(value=settings.VOTED.YES).count()

  @cached_property
  def nays(self):
    return self.votes.filter(value=settings.VOTED.NO).count()

  @cached_property
  def abstains(self):
    return self.votes.filter(value=settings.VOTED.ABSTAIN).count()

  def is_accepted(self):
    if self.yays <= self.nays:
      return False

    # find accepted variant with most yes-votes
    if(self.all_variants):
      most_votes = 0
      for ini in self.all_variants:
        if ini.yays > ini.nays:
         if ini.yays > most_votes:
           most_votes = ini.yays

      # then check if current policy has more than the highest variant
      if self.yays > most_votes:
        return True
      elif self.yays == most_votes:
        # print("We have a tie. Problem! {}".format(self.title))
        # self.notify_moderators("???")

        # XXX prolong vote
        raise Exception("Wait until one of them wins")
      else:
        return False

    # no variants:
    return self.yays > self.nays

  @cached_property
  def all_variants(self):
    if self.variants.count():
      return self.variants.all()

    if self.variant_of:
      variants = [self.variant_of]
      if self.variant_of.variants.count() > 1:
          for ini in self.variant_of.variants.all():
            if ini.id == self.id: continue
            variants.append(ini)

      return variants 
    return []

  # FIXME: cache this
  @cached_property
  def absolute_supporters(self):
    return self.supporting.count()

  @cached_property
  def relative_support(self):
    return self.absolute_supporters / self.quorum * 100

  @cached_property
  def first_supporters(self):
    return self.supporting.filter(first=True).order_by("-created_at")

  @cached_property
  def public_supporters(self):
    return self.supporting.filter(public=True, first=False, initiator=False).order_by("-created_at")

  @cached_property
  def initiators(self):
    return self.supporting.filter(initiator=True).order_by("created_at")

  # XXX not used?
  #@cached_property
  #def custom_cls(self):
  #  return 'item-{} state-{} area-{}'.format(slugify(self.title), slugify(self.state), slugify(self.scope))

  @cached_property
  def allows_abstention(self):
    return True

  @property
  def current_moderations(self):
    return self.moderations.filter(stale=False)

  @property
  def stale_moderations(self):
    return self.moderations.filter(stale=True)

  @cached_property
  def eligible_voter_count(self):

    # set when initiative is closed
    # XXX but when is it closed?
    if self.eligible_voters:
      return self.eligible_voters

    # while open, number of voters == number of users
    # XXX, not so fast...
    else:
      return get_user_model().objects.filter(is_active=True).count()

  def __str__(self):
    return self.title;

  def notify_moderators(self, *args, **kwargs):
    return self.policy_notify([m.user for m in self.moderations.all()], *args, **kwargs)

  def notify_followers(self, *args, **kwargs):

    # while in state staged, we're looking for co-initiators, so followers are
    # only the co-initiators. outside this state, notifying all supporters
    query = [s.user for s in self.supporting.filter(ack=True).all()] if self.state == 'staged' else self.supporters.all()
    return self.policy_notify(query, *args, **kwargs)

  def notify_initiators(self, *args, **kwargs):
    query = [s.user for s in self.initiators]
    return self.policy_notify(query, *args, **kwargs)

  # we wrap pinax:notify onto policy:notify
  def policy_notify(self, recipients, notice_type, extra_context=None, subject=None, **kwargs):
    context = extra_context or dict()
    if subject:
      kwargs['sender'] = subject
      context['target'] = self
    else:
      kwargs['sender'] = self
    notify(recipients, notice_type, context, **kwargs)

# ------------------------------ Initiative ------------------------------------
@reversion.register()
class Initiative(models.Model):

  # fallback 
  STATES = STATES 

  title = models.CharField(max_length=80)
  subtitle = models.CharField(max_length=1024, blank=True)
  state = models.CharField(max_length=1, choices=[
          (STATES.PREPARE, "preparation"),
          (STATES.INCOMING, "new arrivals"),
          (STATES.SEEKING_SUPPORT, "seeking support"),
          (STATES.DISCUSSION, "in discussion"),
          (STATES.FINAL_EDIT, "final edits"),
          (STATES.MODERATION, "with moderation team"),
          (STATES.HIDDEN, "hidden"),
          (STATES.VOTING, "is being voted on"),
          (STATES.ACCEPTED, "was accepted"),
          (STATES.REJECTED, "was rejected")
      ])

  created_at = models.DateTimeField(auto_now_add=True)
  changed_at = models.DateTimeField(auto_now=True)

  summary = models.TextField(blank=True)
  problem = models.TextField(blank=True)
  forderung = models.TextField(blank=True)
  kosten = models.TextField(blank=True)
  fin_vorschlag = models.TextField(blank=True)
  arbeitsweise = models.TextField(blank=True)
  init_argument = models.TextField(blank=True)

  einordnung = models.CharField(max_length=50, choices=settings.CATEGORIES.CONTEXT_CHOICES)
  ebene = models.CharField(max_length=100, choices=settings.CATEGORIES.SCOPE_CHOICES)
  bereich = models.CharField(max_length=60, choices=settings.CATEGORIES.TOPIC_CHOICES)

  went_public_at = models.DateField(blank=True, null=True)
  went_to_discussion_at = models.DateField(blank=True, null=True)
  went_to_voting_at = models.DateField(blank=True, null=True)
  was_closed_at = models.DateField(blank=True, null=True)

  variant_of = models.ForeignKey('self', blank=True, null=True, default=None, related_name="variants")

  supporters = models.ManyToManyField(User, through="Supporter")
  eligible_voters = models.IntegerField(blank=True, null=True)

  @cached_property
  def slug(self):
    return slugify(self.title)

  @cached_property
  def versions(self):
    return Version.objects.get_for_object(self)

  @cached_property
  def sort_index(self):
    timezone = self.created_at.tzinfo
    if self.was_closed_at: #recently closed first
      return datetime.today().date() - self.was_closed_at

    elif self.end_of_this_phase: #closest to deadline first
      return self.end_of_this_phase - datetime.today().date()

    else: #newest first
      return datetime.now(timezone) - self.created_at

  @cached_property
  def ready_for_next_stage(self):

    if self.state in [Initiative.STATES.INCOMING, Initiative.STATES.MODERATION]:
      return self.supporting.filter(initiator=True, ack=True).count() == INITIATORS_COUNT

    if self.state in [Initiative.STATES.PREPARE, Initiative.STATES.FINAL_EDIT]:
      #three initiators and no empty text fields
      return (self.supporting.filter(initiator=True, ack=True).count() == INITIATORS_COUNT and
        self.title and
        self.subtitle and
        self.arbeitsweise and
        self.bereich and
        self.ebene and
        self.einordnung and
        self.fin_vorschlag and
        self.forderung and
        self.init_argument and
        self.kosten and
        self.problem and
        self.summary)

    if self.state == Initiative.STATES.SEEKING_SUPPORT:
      return self.supporting.filter().count() >= self.quorum

    if self.state == Initiative.STATES.DISCUSSION:
      # there is nothing we have to accomplish
      return True

    if self.state == Initiative.STATES.VOTING:
      # there is nothing we have to accomplish
      return True

    return False

  @cached_property
  def end_of_this_phase(self):
    week = timedelta(days=7)
    halfyear = timedelta(days=183)

    if self.was_closed_at:
      return self.was_closed_at + halfyear # Half year later.

    if self.went_public_at:
      if self.went_public_at < SPEED_PHASE_END:
        if self.state == Initiative.STATES.SEEKING_SUPPORT:
          if self.variant_of:
            if self.variant_of.went_to_discussion_at:
              return self.variant_of.went_to_discussion_at + (2 * week)
          if self.ready_for_next_stage:
            return self.went_public_at + week
          return self.went_public_at + halfyear

        elif self.state == Initiative.STATES.DISCUSSION:
          base = self.went_to_discussion_at
          if self.variant_of:
            if self.variant_of.went_to_discussion_at:
              base = self.variant_of.went_to_discussion_at
          return base + (2 * week)

        elif self.state == 'e':
          return self.went_to_discussion_at + (3 * week)

        elif self.state == 'v':
          return self.went_to_voting_at + week

      else:
        if self.state == Initiative.STATES.SEEKING_SUPPORT:
          if self.variant_of:
            if self.variant_of.went_to_discussion_at:
              return self.variant_of.went_to_discussion_at +( 2 * week)
          if self.ready_for_next_stage:
            return self.went_public_at + (2 * week)

        elif self.state == 'd':
          return self.went_to_discussion_at + (3 * week)

        elif self.state == 'e':
          return self.went_to_discussion_at + (5 * week)

        elif self.state == 'v':
          return self.went_to_voting_at + (3 * week)

    return None

  @cached_property
  def quorum(self):
    return Quorum.current_quorum()

  @property
  def show_supporters(self):
    return self.state in [self.STATES.PREPARE, self.STATES.INCOMING, self.STATES.SEEKING_SUPPORT]

  @property
  def show_debate(self):
    return self.state in [self.STATES.DISCUSSION, self.STATES.FINAL_EDIT, self.STATES.MODERATION, self.STATES.VOTING, self.STATES.ACCEPTED, self.STATES.REJECTED]

  @cached_property
  def yays(self):
    return self.votes.filter(value=VOTED.YES).count()

  @cached_property
  def nays(self):
    return self.votes.filter(value=VOTED.NO).count()

  @cached_property
  def abstains(self):
    return self.votes.filter(value=VOTED.ABSTAIN).count()

  def is_accepted(self):
    if self.yays <= self.nays: #always reject if too few yays
      return False

    if(self.all_variants):
      most_votes = 0
      for ini in self.all_variants: #find the variant that
        if ini.yays > ini.nays:       # was accepted
         if ini.yays > most_votes:   # and has the most yay votes
            most_votes = ini.yays
      # then check if current initiative has more than the highest variant
      if self.yays > most_votes:
        return True
      elif self.yays == most_votes:
        print("We have a tie. Problem! {}".format(self.title))
        # self.notify_moderators("???")
        raise Exception("Wait until one of them wins")
      else:
        return False

    # no variants:
    return self.yays > self.nays

  @cached_property
  def all_variants(self):
    if self.variants.count():
      return self.variants.all()

    if self.variant_of:
      variants = [self.variant_of]
      if self.variant_of.variants.count() > 1:
        for ini in self.variant_of.variants.all():
          if ini.id == self.id: continue
          variants.append(ini)

      return variants 

    return []

  # FIXME: cache this
  @cached_property
  def absolute_supporters(self):
    return self.supporting.count()

  @cached_property
  def relative_support(self):
    return self.absolute_supporters / self.quorum * 100

  @cached_property
  def first_supporters(self):
    return self.supporting.filter(first=True).order_by("-created_at")

  @cached_property
  def public_supporters(self):
    return self.supporting.filter(public=True, first=False, initiator=False).order_by("-created_at")

  @cached_property
  def initiators(self):
    return self.supporting.filter(initiator=True).order_by("created_at")

  @cached_property
  def custom_cls(self):
    return 'item-{} state-{} area-{}'.format(slugify(self.title), slugify(self.state), slugify(self.bereich))

  @cached_property
  def allows_abstention(self):
    if self.went_to_voting_at:
      return self.went_to_voting_at > ABSTENTION_START
    else:
      return True

  @property
  def current_moderations(self):
      return self.moderations.filter(stale=False)

  @property
  def stale_moderations(self):
    return self.moderations.filter(stale=True)

  @cached_property
  def eligible_voter_count(self):
    if self.eligible_voters: #is set when initiative is closed
      return self.eligible_voters
    else: # while open, number of voters == number of users
      return get_user_model().objects.filter(is_active=True).count()

  def __str__(self):
    return self.title;

  def notify_moderators(self, *args, **kwargs):
    return self.notify([m.user for m in self.moderations.all()], *args, **kwargs)

  def notify_followers(self, *args, **kwargs):
    query = [s.user for s in self.supporting.filter(ack=True).all()] if self.state == 'p' else self.supporters.all()
    return self.notify(query, *args, **kwargs)

  def notify_initiators(self, *args, **kwargs):
    query = [s.user for s in self.initiators]
    return self.notify(query, *args, **kwargs)

  def notify(self, recipients, notice_type, extra_context=None, subject=None, **kwargs):
    context = extra_context or dict()
    if subject:
      kwargs['sender'] = subject
      context['target'] = self
    else:
      kwargs['sender'] = self

    init_notify(recipients, notice_type, context, **kwargs)

# ---------------------------------- Vote ---------------.----------------------
class Vote(models.Model):

  class Meta:
    unique_together = (("user", "initiative"),)

  created_at = models.DateTimeField(auto_now_add=True)
  changed_at = models.DateTimeField(auto_now=True)
  user = models.ForeignKey(User)
  initiative = models.ForeignKey(Initiative, related_name="votes")
  value = models.IntegerField(choices=settings.VOTED_CHOICES)
  reason = models.CharField(max_length=100, blank=True)

  policy = models.ForeignKey(Policy, related_name="policy_votes")

  @property
  def nay_survey_options(self):
    return [
      _("Does not conform to my convictions."), 
      _("Is not important enough."),
      _("Is not specific enough."),
      _("Is not mature enough (in terms of contents.)"),
      _("Contains a detail, I do not agree with."),
      "".join([_("Does not fit to:"), settings.PLATFORM_TITLE_ACRONYM]),
      _("Is difficult to stand in for."),
      _("Is no longer relevant."),
    ]

  @cached_property
  def in_favor(self):
    return self.value == settings.VOTED.YES

  @cached_property
  def against(self):
    return self.value == settings.VOTED.NO

  @cached_property
  def abstained(self):
    return self.value == settings.VOTED.ABSTAIN

# -------------------------------- Quorum ---------------.----------------------
# XXX policy will use it's own Quorum, this one is set using management command
class Quorum(models.Model):
  created_at = models.DateTimeField(auto_now_add=True)
  quorum = models.IntegerField(null=0)

  @classmethod
  def current_quorum(cls):
    quorum_list = cls.objects.order_by("-created_at").values("quorum")
    if len(quorum_list) > 0:
      return quorum_list.first()["quorum"]
    return 0

# ------------------------------- Supporter -------------.----------------------
class Supporter(models.Model):

  class Meta:
    unique_together = (("user", "initiative"),)

  created_at = models.DateTimeField(auto_now_add=True)
  user = models.ForeignKey(User)
  initiative = models.ForeignKey(Initiative, related_name="supporting")

  # here we come
  policy = models.ForeignKey(Policy, related_name="policy_supporters")

  # whether this initiator has acknowledged they are
  ack = models.BooleanField(default=False)
  initiator = models.BooleanField(default=False)
  public = models.BooleanField(default=True)
  first = models.BooleanField(default=False)


# ---------------------------------- Like -------------.------------------------
class Like(models.Model):

  class Meta:
    unique_together = (("user", "target_type", "target_id"),)

  created_at = models.DateTimeField(auto_now_add=True)
  user = models.ForeignKey(User)

  target_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
  target_id = models.IntegerField()
  target = GenericForeignKey('target_type', 'target_id')

# -------------------------------- Likeable ------------------------------------
class Likeable(models.Model):

  class Meta:
    abstract = True

  likes_count = models.IntegerField(default=0) # FIXME: should be updated per DB-trigger
  likes = GenericRelation(Like, content_type_field='target_type', object_id_field='target_id')

# -------------------------------- Comment -------------------------------------
# XXX why does this inherit from Likeable and not Commentable
class Comment(Likeable):

  type = "comment"
  created_at = models.DateTimeField(auto_now_add=True)
  changed_at = models.DateTimeField(auto_now=True)
  user = models.ForeignKey(User)

  target_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
  target_id = models.IntegerField()
  target = GenericForeignKey('target_type', 'target_id')

  text = models.CharField(max_length=500)

  @property
  def unique_id(self):
    return "{}-{}".format(self.type, self.id)

# ----------------------------- Commentable ------------------------------------
class Commentable(models.Model):

  class Meta:
    abstract = True

  # FIXME: should be updated per DB-trigger
  comments_count = models.IntegerField(default=0)
  comments = GenericRelation(Comment, content_type_field='target_type', object_id_field='target_id')


# ------------------------------- Response -------------------------------------
class Response(Likeable, Commentable):
  
  class Meta:
    abstract = True

  created_at = models.DateTimeField(auto_now_add=True)
  changed_at = models.DateTimeField(auto_now=True)

  # can't we just write Response instead of %(class)ss? no, we can't,
  # because Response is inherited from and heirs have different names
  user = models.ForeignKey(User, related_name="%(class)ss")

  # XXX this needs a target-id and target-type because only one will be defined
  # and both cannot be null
  initiative = models.ForeignKey(Initiative, related_name="%(class)ss")
  #policy = models.ForeignKey(Policy, related_name="%(class)ss")
  # XXX 
  #destination_type
  #destination_id 

  @property
  def unique_id(self):
    return "{}-{}".format(self.type, self.id)

# ------------------------------- Proposeal ------------------------------------
class Argument(Response):

  class Meta:
    abstract = True

  title = models.CharField(max_length=140)
  text = models.CharField(max_length=500)

# ------------------------------- Proposeal ------------------------------------
class Proposal(Response):

  type = "proposal"
  icon = False
  title = models.CharField(max_length=140)
  text = models.CharField(max_length=1024)

# ---------------------------------- Pro ---------------------------------------
class Pro(Argument):

  type = "pro"
  css_class = "success"
  icon = "thumb_up"

  def __str__(self):
    return "".join([_("In Favor"), ": {}".format(self.title)])

# -------------------------------- Contra --------------------------------------
class Contra(Argument):

    type = "contra"
    css_class = "danger"
    icon = "thumb_down"

    def __str__(self):
      return "".join([_("Against"), ": {}".format(self.title)])

# ------------------------------ Moderation ------------------------------------
class Moderation(Response):

  type = "moderation"
  stale = models.BooleanField(default=False)
  vote = models.CharField(max_length=1, choices=settings.MODERATED_CHOICES)
  text = models.CharField(max_length=500, blank=True)

