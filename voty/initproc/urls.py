# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initproc urls
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------
from django.conf.urls import url
from django.views import generic
from django.utils.translation import ugettext as _
from . import views

urlpatterns = [
  url(r'^(?P<filename>(robots.txt)|(humans.txt))$', views.crawler, name='crawler'),

  # home/i18n
  url(r"^$", views.index, name="home"),

  # about (ueber) is not static
  url(r"^about/$", views.about, name="about"),
  url(r"^account/language/$", views.account_language, name="account_language"),

  # autocomplete for invite supporters
  url(r"^user_autocomplete$", views.UserAutocomplete.as_view(), name="user_autocomplete"),

  # policies

  # undo, must go first, else policy_item will mtch
  url(r'^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/undo/(?P<uidb64>[0-9A-Za-z_\\-\\=]+)/(?P<token>[0-9A-Za-z]{1,20})/$', views.policy_undo, name="policy_undo"),

  url(r"^policy/new$", views.policy_new, name="policy_new"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/$", views.policy_item, name="policy_item"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/edit$", views.policy_edit, name="policy_edit"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/support$", views.policy_support, name="policy_support"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/refrain$", views.policy_refrain, name="policy_refrain"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/acknowledge_support/(?P<user_id>.*)$", views.policy_acknowledge_support, name="policy_acknowledge_support"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/remove_support/(?P<user_id>.*)$", views.policy_remove_support, name="policy_remove_support"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/invite/(?P<invite_type>.*)$", views.policy_invite, name="policy_invite"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/apply", views.policy_apply, name="policy_apply"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/stage$", views.policy_stage, name="policy_stage"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/validate$", views.policy_validate, name="policy_validate"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/reject$", views.policy_reject, name="policy_reject"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/discuss$", views.policy_discuss, name="policy_discuss"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/close$", views.policy_close, name="policy_close"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/challenge$", views.policy_challenge, name="policy_challenge"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/delete$", views.policy_delete, name="policy_delete"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/undelete$", views.policy_undelete, name="policy_undelete"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/unhide$", views.policy_unhide, name="policy_unhide"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/submit$", views.policy_submit, name="policy_submit"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/evaluate", views.policy_evaluate, name="policy_evaluate"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/review", views.policy_review, name="policy_review"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/finalise", views.policy_finalise, name="policy_finalise"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/proposal_new$", views.policy_proposal_new, name="policy_proposal_new"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/argument_new$", views.policy_argument_new, name="policy_argument_new"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/argument_solve/(?P<target_type>.*)/(?P<target_id>\d+)$", views.policy_argument_solve, name="policy_argument_solve"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/argument_details/(?P<target_type>.*)/(?P<target_id>\d+)$", views.policy_argument_details, name="policy_argument_details"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/feedback/(?P<target_id>\d+)$", views.policy_feedback, name="policy_feedback"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/stale_feedback$", views.policy_stale_feedback, name="policy_stale_feedback"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/stale_proposals$", views.policy_stale_proposals, name="policy_stale_proposals"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/history/(?P<version_id>\d+)$", views.policy_history, name="policy_history"),
  url(r"^policy/(?P<policy_id>\d+)(?:-(?P<slug>.*))?/history_delete/(?P<version_id>\d+)$", views.policy_history_delete, name="policy_history_delete"),
  url(r"^comment/(?P<target_type>[^/]+)/(?P<target_id>[^/?#]+)", views.target_comment, name="target_comment"),
  url(r"^like/(?P<target_type>.*)/(?P<target_id>\d+)$", views.target_like, name="target_like"),
  url(r"^unlike/(?P<target_type>.*)/(?P<target_id>\d+)$", views.target_unlike, name="target_unlike"),
  url(r"^delete/(?P<target_type>.*)/(?P<target_id>\d+)$", views.target_delete, name="target_delete"),
  url(r"^edit/(?P<target_type>.*)/(?P<target_id>\d+)$", views.target_edit, name="target_edit"),

  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/support$", views.support, name="support"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/ack_support$", views.ack_support, name="ack_support"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/rm_support$", views.rm_support, name="rm_support"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/submit_to_committee$", views.submit_to_committee, name="submit_to_committee"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/new_argument$", views.new_argument, name="new_argument"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/new_proposal$", views.new_proposal, name="new_proposal"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/new_moderation$", views.moderate, name="moderate"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/vote$", views.vote, name="vote"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/reset_vote$", views.reset_vote, name="reset_vote"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/compare/(?P<version_id>\d+)$", views.compare, name="compare"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/invite/(?P<invite_type>.*)$", views.invite, name="invite"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/moderation/(?P<target_id>\d+)$", views.show_moderation, name="show_moderation"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?/(?P<target_type>.*)/(?P<target_id>\d+)$", views.show_resp, name="show_resp"),
  url(r"^initiative/(?P<init_id>\d+)(?:-(?P<slug>.*))?$", views.item, name="initiative_item"),
]

