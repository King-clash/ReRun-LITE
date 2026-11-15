from .any_quest import AnyQuestScript
from .arena import ArenaScript
from .chain import ChainScript
from .compendium_counter import CompendiumCounterScript
from .gc_area import GcAreaScript
from .helper_rewards import HelperRewardsScript
from .crest import CrestScript
from .grand_crusade import GrandCrusadeScript
from .login_mail import LoginMailScript
from .mines import MinesScript
from .multi_farm import MultiFarmScript
from .queue_gc_crest import QueueScript
from .raids import RaidGuestScript, RaidHostScript, RaidTicketsScript
from .secret_equip import SecretEquipScript

# Order shown in the UI: tested scripts first, then the Beta ones.
SCRIPTS = {cls.ID: cls for cls in (
    AnyQuestScript, CrestScript, LoginMailScript,
    ArenaScript, GrandCrusadeScript, GcAreaScript, QueueScript, MinesScript, MultiFarmScript,
    HelperRewardsScript, RaidTicketsScript, RaidHostScript, RaidGuestScript, SecretEquipScript,
    CompendiumCounterScript, ChainScript,
)}
