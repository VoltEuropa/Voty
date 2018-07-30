from datetime import date
from django.utils.translation import ugettext_lazy as _

class STATES:
    """
    The states an initiative can have
    """
    PREPARE = 'p'
    INCOMING = 'i'
    SEEKING_SUPPORT = 's'
    DISCUSSION = 'd'
    FINAL_EDIT = 'e'
    MODERATION = 'm'
    HIDDEN = 'h'
    VOTING = 'v'
    ACCEPTED = 'a'
    REJECTED = 'r'


PUBLIC_STATES = [STATES.SEEKING_SUPPORT,
                 STATES.DISCUSSION,
                 STATES.FINAL_EDIT,
                 STATES.VOTING,
                 STATES.ACCEPTED,
                 STATES.REJECTED]

TEAM_ONLY_STATES = [STATES.INCOMING,
                    STATES.MODERATION,
                    STATES.HIDDEN]

class VOTED:
    """
    The possibilities for casting a vote
    """
    NO = 0
    YES = 1
    ABSTAIN = 2


COMPARING_FIELDS = [
    'title', 'subtitle',  "summary", "problem", "forderung", "kosten",
    "fin_vorschlag", "arbeitsweise", "init_argument",
    "einordnung", "ebene", "bereich",
]

ABSTENTION_START = date(2017, 12, 1) # Everything published after this has abstentions
SPEED_PHASE_END = date(2017, 8, 21) # Everything published before this has speed phase
INITIATORS_COUNT = 3

MINIMUM_MODERATOR_VOTES = 5
MINIMUM_FEMALE_MODERATOR_VOTES = 3
MINIMUM_DIVERSE_MODERATOR_VOTES = 2
