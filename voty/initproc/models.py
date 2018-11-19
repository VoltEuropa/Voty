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
from django.utils import six
from reversion.models import Version
from functools import reduce


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
import collections

# =============================== HELPERS ======================================

# ------------------------ Build Class field dict .-----------------------------
def _create_class_field_dict(field_dict):
  response = collections.OrderedDict({})

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
# allows to create dynamic abstract classes from settings/ini file, more info,
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
print(_create_class_field_dict(settings.PLATFORM_POLICY_BASE_CONFIG))
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

# -------------------------------- Policy --------------------------------------
@reversion.register()
class Policy(PolicyBase):

  # content fields provided via abstract class (init.ini) = configurable

  # there is so much text stored on an initiative/policy that state can also be
  # human-readable = we don't use single characters, max-length:20
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
  changed_at = models.DateTimeField(auto_now=True)

  # changed published to validated and closed (not used, no?) to published
  was_staged_at = models.DateTimeField(auto_now=True)
  was_validated_at = models.DateTimeField(blank=True, null=True)
  went_in_discussion_at = models.DateTimeField(blank=True, null=True)
  went_in_vote_at = models.DateTimeField(blank=True, null=True)
  was_published_at = models.DateTimeField(blank=True, null=True)
  was_rejected_at = models.DateTimeField(blank=True, null=True)
  was_challenged_at = models.DateTimeField(blank=True, null=True)
  was_reopened_at = models.DateTimeField(blank=True, null=True)

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
      return datetime.today() - self.was_published_at

    # closest to deadline first
    elif self.end_of_this_phase:
      return self.end_of_this_phase - datetime.today()

    # newest first
    else:
      return datetime.now(timezone) - self.was_staged_at

  # ---------------------------- end of phase ----------------------------------
  # this returns time(!) when phase is over. Compare against it elsewhere!
  @cached_property
  def end_of_this_phase(self):

    # rejection needs to rest 180 days
    if self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.REJECTED,
      settings.PLATFORM_POLICY_STATE_DICT.CHALLENGED
    ]:
      return self.was_rejected_at + \
        timedelta(days=int(settings.PLATFORM_POLICY_RELAUNCH_MORATORIUM_DAYS))

    # support takes between MIN and MAX days with a COOLDOWN after reaching support
    if self.state == settings.PLATFORM_POLICY_STATE_DICT.VALIDATED:
      lower_bound = self.was_validated_at + \
        timedelta(days=int(settings.PLATFORM_POLICY_SUPPORT_MINIMUM_DAYS))

      # if support is reached, wait cooldown days
      if self.supporting_policy.filter().count() >= self.quorum:
        return lower_bound + timedelta(days=int(settings.PLATFORM_POLICY_SUPPORT_COOLDOWN_DAYS))

      # minimum time not reached
      if datetime(lower_bound.year, lower_bound.month, lower_bound.day) > datetime.now():
        return lower_bound

      return self.was_validated_at + timedelta(int(settings.PLATFORM_POLICY_SUPPORT_MAXIMUM_DAYS))

    # discussion takes DISCUSSION days
    elif self.state == settings.PLATFORM_POLICY_STATE_DICT.DISCUSSED:
      return self.went_in_discussion_at + \
        timedelta(int(settings.PLATFORM_POLICY_DISCUSSION_DAYS))

    # vote takes VOTE days
    elif self.state == settings.PLATFORM_POLICY_STATE_DICT.VOTED:
      return self.went_in_vote_at + \
        timedelta(int(settings.PLATFORM_POLICY_VOTING_DAYS))

    return None


  # checked by multiplying field length, because one empty field will fail, eg 
  # len(int[17, 1123, 0]) = 17*1123*0 = 0 = FAIL
  @property
  def required_fields(self):
    return reduce(lambda x, y: x*y, [len(getattr(self, f.name, "")) for f in PolicyBase._meta.get_fields()])

  
  # XXX if an initiator leaves/does not confirm an edit in a non-invite state, 
  # we are blocked
  @property
  def required_initiators(self):
    return self.supporting_policy.filter(initiator=True, ack=True).count() >= int(settings.PLATFORM_POLICY_INITIATORS_COUNT)

  # XXX name "required_moderations" already used.
  # max number of moderations without pending reviews ("r" ~ request info) cannot 
  # use current, because these do not include stale moderations and for challenged 
  # and finalised, stale moderations count. Must also be aware of previously
  # challenged policy, so we need to check by date again
  @property
  def required_evaluations(self):
    moderations = self.policy_moderations.exclude(vote="r")
    if self.state == settings.PLATFORM_POLICY_STATE_DICT.FINALISED:
      moderations = moderations.filter(stale=False)
    if self.was_reopened_at:
      return len([x for x in moderations if x.changed_at > self.was_reopened_at]) >= self.required_moderations
    else:
      return moderations.count() >= self.required_moderations

  # ----------------------- ready for next phase -------------------------------
  # ready for next stage says when ready, proceed says continue or close
  @property
  def ready_for_next_stage(self):

    if self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.STAGED,
      settings.PLATFORM_POLICY_STATE_DICT.REVIEWED,
    ]:
      return (self.required_initiators and self.required_fields)

    # moderation states requires complete policy, initiators and number of mods
    if self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.SUBMITTED,
      settings.PLATFORM_POLICY_STATE_DICT.INVALIDATED,
      settings.PLATFORM_POLICY_STATE_DICT.CHALLENGED,
      settings.PLATFORM_POLICY_STATE_DICT.FINALISED,
    ]:
      return (self.required_initiators and self.required_fields and self.required_evaluations)

    # seeking support requires supporters and time
    if self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.VALIDATED,
      settings.PLATFORM_POLICY_STATE_DICT.VOTED
    ]:
      return datetime.now() > self.end_of_this_phase()
      
    # discussion requires time
    if self.state == settings.PLATFORM_POLICY_STATE_DICT.DISCUSSED:
      return datetime.now(self.created_at.tzinfo) > self.went_in_discussion_at + \
        timedelta(days=int(settings.PLATFORM_POLICY_DISCUSSION_DAYS))

    # rejected takes time
    if self.state == settings.PLATFORM_POLICY_STATE_DICT.REJECTED:
      return datetime.now(self.created_at.tzinfo) > self.was_rejected_at + \
        timedelta(days=int(settings.PLATFORM_POLICY_RELAUNCH_MORATORIUM_DAYS))

    # nothing to do
    if self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.DRAFT,
      settings.PLATFORM_POLICY_STATE_DICT.CONCLUDED,
    ]:
      return True

    return False

  # ---------------------- proceed to next phase -------------------------------
  # ready for next stage says when ready, proceed says continue or close
  @property
  def ready_to_proceed(self):

    if self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.SUBMITTED,
      settings.PLATFORM_POLICY_STATE_DICT.INVALIDATED,
      settings.PLATFORM_POLICY_STATE_DICT.CHALLENGED,
      settings.PLATFORM_POLICY_STATE_DICT.FINALISED,
    ]:
      moderations = self.policy_moderations.all()

      # finalised must ignore stale reviews
      if self.state == settings.PLATFORM_POLICY_STATE_DICT.FINALISED:
        moderations = moderations.filter(stale=False)

      # reopened must also ignore previous reviews
      if self.was_reopened_at:
        return len([x for x in moderations.filter(vote="y") if x.changed_at > self.was_reopened_at]) > \
          len([x for x in moderations.filter(vote="n") if x.changed_at > self.was_reopened_at])
      else:
        return moderations.filter(vote="y").count() > moderations.filter(vote="n").count()

    if self.state == settings.PLATFORM_POLICY_STATE_DICT.VALIDATED:
      return self.supporting_policy.filter().count() >= self.quorum

    if self.state == settings.PLATFORM_POLICY_STATE_DICT.CONCLUDED:
      return self.is_accepted()

    return False

  @cached_property
  def quorum(self):
    return Quorum.current_quorum()

  @property
  def show_supporters(self):
    return self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.STAGED,
      settings.PLATFORM_POLICY_STATE_DICT.SUBMITTED,
      settings.PLATFORM_POLICY_STATE_DICT.VALIDATED,
      settings.PLATFORM_POLICY_STATE_DICT.REVIEWED,
    ]

  @property
  def show_vote(self):
    return self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.VOTED
    ]

  @property
  def show_debate(self):
    return self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.STAGED,
      settings.PLATFORM_POLICY_STATE_DICT.DISCUSSED,
      settings.PLATFORM_POLICY_STATE_DICT.REVIEWED,
      settings.PLATFORM_POLICY_STATE_DICT.VOTED,
      settings.PLATFORM_POLICY_STATE_DICT.CONCLUDED,
      settings.PLATFORM_POLICY_STATE_DICT.PUBLISHED,
      settings.PLATFORM_POLICY_STATE_DICT.CLOSED,
    ]

  @cached_property
  def yays(self):
    return self.policy_votes.filter(value=settings.VOTED.YES).count()

  @cached_property
  def nays(self):
    return self.policy_votes.filter(value=settings.VOTED.NO).count()

  @cached_property
  def abstains(self):
    return self.policy_votes.filter(value=settings.VOTED.ABSTAIN).count()

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
    return self.supporting_policy.filter(ack=True).count()

  @cached_property
  def relative_support(self):
    return self.absolute_supporters / self.quorum * 100

  # XXX not used?
  #@cached_property
  #def first_supporters(self):
  #  return self.supporting_policy.filter(first=True).order_by("-created_at")

  @cached_property
  def public_supporters(self):
    return self.supporting_policy.filter(public=True, ack=True, first=False, initiator=False).order_by("-created_at")

  @cached_property
  def initiators(self):
    return self.supporting_policy.filter(initiator=True).order_by("created_at")

  # used by simpleFormVerifier
  @cached_property
  def custom_cls(self):
    return 'item-{} state-{} area-{}'.format(slugify(self.title), slugify(self.state), slugify(self.scope))

  @cached_property
  def allows_abstention(self):
    return True

  @property
  def total_moderators(self):
    group = settings.PLATFORM_GROUP_VALUE_TITLE_LIST
    if isinstance(group, six.string_types):
      groups = (group, )
    else:
      groups = group
    return User.objects.filter(groups__name__in=groups).distinct().count()

  @property
  def required_moderations(self):

    minimum_moderators_by_percent = round(int(int(self.total_moderators) * int(settings.PLATFORM_MODERATION_SETTING_LIST.MINIMUM_MODERATOR_PERCENTAGE)/100))
    minimum_moderators_by_count = int(settings.PLATFORM_MODERATION_SETTING_LIST.MINIMUM_MODERATOR_VOTES)

    # we can include the rejected here, because we don't show the initial 
    # reviews required anymore after the policy has been rejected. So we can
    # calculate the total for a challenge and see whether challenge is possible.
    if self.state in [
      settings.PLATFORM_POLICY_STATE_DICT.CHALLENGED,
      settings.PLATFORM_POLICY_STATE_DICT.REJECTED,
    ]:
      minimum_moderators_by_count += int(settings.PLATFORM_MODERATION_SETTING_LIST.MINIMUM_ADDED_VOTES_FOR_CHALLENGE)
  
    if self.state == settings.PLATFORM_POLICY_STATE_DICT.REVIEWED:
      minimum_moderators_by_count += int(settings.PLATFORM_MODERATION_SETTING_LIST.MINIMUM_ADDED_VOTES_FOR_REVIEW)

    if minimum_moderators_by_percent >= minimum_moderators_by_count:
      return minimum_moderators_by_percent

    # in case of a patt, 1 less
    if minimum_moderators_by_count % 2 == 0:
      return minimum_moderators_by_count - 1

    # in case not enough moderators, we ask for a board decision?
    # if minimum_moderators_by_count > total_moderators:

    return minimum_moderators_by_count

  @property
  def current_moderations(self):
    return self.policy_moderations.filter(stale=False)

  @property
  def stale_moderations(self):
    return self.policy_moderations.filter(stale=True)

  @cached_property
  def eligible_voter_count(self):

    # XXX set when policy is closed - but when is it closed?
    if self.eligible_voters:
      return self.eligible_voters

    # XXX while open, number of voters == number of users -> not so fast...
    else:
      return get_user_model().objects.filter(is_active=True).count()

  def __str__(self):
    return self.title;

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

  # XXX why did I put responses/supporters here?
  #responses = GenericRelation(Response, content_type_field='target_type', object_id_field='target_id')
  #supporters = GenericRelation(Supporter, content_type_field='target_type', object_id_field='target_id', related_query_name="supporting")
  #votes = GenericRelation(Vote, content_type_field='target_type', object_id_field='target_id')

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
      return datetime.today() - self.was_closed_at

    elif self.end_of_this_phase: #closest to deadline first
      return self.end_of_this_phase - datetime.today()

    else: #newest first
      return datetime.now(timezone) - self.created_at

  @cached_property
  def ready_for_next_stage(self):

    if self.state in [Initiative.STATES.INCOMING, Initiative.STATES.MODERATION]:
      return self.supporting_initiative.filter(initiator=True, ack=True).count() == INITIATORS_COUNT

    if self.state in [Initiative.STATES.PREPARE, Initiative.STATES.FINAL_EDIT]:
      #three initiators and no empty text fields
      return (self.supporting_initiative.filter(initiator=True, ack=True).count() == INITIATORS_COUNT and
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
      return self.supporting_initiative.filter().count() >= self.quorum

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
    return self.supporting_initiative.count()

  @cached_property
  def relative_support(self):
    return self.absolute_supporters / self.quorum * 100

  @cached_property
  def first_supporters(self):
    return self.supporting_initiative.filter(first=True).order_by("-created_at")

  @cached_property
  def public_supporters(self):
    return self.supporting_initiative.filter(public=True, first=False, initiator=False).order_by("-created_at")

  @cached_property
  def initiators(self):
    return self.supporting_initiative.filter(initiator=True).order_by("created_at")

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
    query = [s.user for s in self.supporting_initiative.filter(ack=True).all()] if self.state == 'p' else self.supporters.all()
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

# ------------------------------- Supporter -------------.----------------------
class Supporter(models.Model):

  class Meta:
    #unique_together = (("user", "target_type", "target_id"),)
    unique_together = (("user", "initiative", "policy"),)

  created_at = models.DateTimeField(auto_now_add=True)
  user = models.ForeignKey(User)

  initiative = models.ForeignKey(Initiative, related_name="supporting_initiative", null=True)
  policy = models.ForeignKey(Policy, related_name="supporting_policy", null=True)

  # Can't use GenericRelation because of ManyToMany, through and related_name...
  #target_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
  #target_id = models.IntegerField()
  #target = GenericForeignKey('target_type', 'target_id')

  # whether this initiator has acknowledged they are
  ack = models.BooleanField(default=False)
  initiator = models.BooleanField(default=False)
  public = models.BooleanField(default=True)
  first = models.BooleanField(default=False)

# ---------------------------------- Vote ---------------.----------------------
class Vote(models.Model):

  class Meta:
    #unique_together = (("user", "target_type", "target_id"),)
    unique_together = (("user", "initiative", "policy"),)

  created_at = models.DateTimeField(auto_now_add=True)
  changed_at = models.DateTimeField(auto_now=True)
  user = models.ForeignKey(User)
  value = models.IntegerField(choices=settings.VOTED_CHOICES)
  reason = models.CharField(max_length=100, blank=True)

  initiative = models.ForeignKey(Initiative, related_name="initiative_votes", null=True)
  policy = models.ForeignKey(Policy, related_name="policy_votes", null=True)

  # caching this make inconsistent layouts when voting and retracting
  @property
  def in_favor(self):
    return self.value == settings.VOTED.YES

  @property
  def against(self):
    return self.value == settings.VOTED.NO

  @property
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

# ------------------------------- Response -------------------------------------
class Response(Likeable, Commentable):

  class Meta:
    abstract = True

  created_at = models.DateTimeField(auto_now_add=True)
  changed_at = models.DateTimeField(auto_now=True)

  # we can't just write "Response" instead of %(class)ss, because Response 
  # is inherited from and heirs have different names
  user = models.ForeignKey(User, related_name="%(class)ss")

  # for backcompat, allow null, so we need to update queries for responses to 
  # include source type and exclude the ones which are null. alternatively use 
  # generic foreign key which can point to both initiative and policy. this
  # seems overkill, though and requires more migration than the below change
  # https://stackoverflow.com/a/881912/
  # https://docs.djangoproject.com/en/1.10/ref/contrib/contenttypes/#generic-relations
  # https://simpleisbetterthancomplex.com/tutorial/2016/10/13/how-to-use-generic-relations.html

  # ISSUE #1: what to do with existing data in initiative
  # ISSUE #2: how to use GenericForeignKey while keeping Response abstract,
  #           because we don't want a new table for convenience storing data
  #           that might as well be stored somewhere else
  initiative = models.ForeignKey(Initiative, related_name="initiative_%(class)ss", null=True)
  policy = models.ForeignKey(Policy, related_name="policy_%(class)ss", null=True)
  #source_type = models.CharField(
  #  max_length=1,
  #  choices=[("i", _("Initiative")), ("p", _("Policy"))],
  #  default="i"
  #)
  #target_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
  #target_id = models.IntegerField()
  #target = GenericForeignKey('target_type', 'target_id')

  @property
  def unique_id(self):
    return "{}-{}-{}".format("policy" if self.policy else "initiative", self.type, self.id)
    #return "{}-{}".format(self.type, self.id)
    #return "{}-{}-{}-{}".format(self.type, self.id, self.target_type, self.target_id)
# ------------------------------- Argument -------------------------------------
class Argument(Response):

  class Meta:
    abstract = True

  title = models.CharField(max_length=140)
  text = models.CharField(max_length=500)

# ------------------------------- Proposeal ------------------------------------
class Proposal(Response):

  type = "proposal"
  icon = False
  stale = models.BooleanField(default=False)
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
  blockers = models.CharField(max_length=100, blank=True, null=True)
  vote = models.CharField(max_length=1, choices=settings.PLATFORM_MODERATION_CHOICE_LIST)
  text = models.CharField(max_length=500, blank=True)
