"""Editorial learning brain — major subsystem.

Always learning:
  * daily from top podcasts / talking heads / long-form / shorts
  * from every rated edit (-1 bad … 20 perfect)
  * from every contextual dislike (never-again rules)

Persistence: ``data/learning/store.json`` + Obsidian notes under
``context_docs/obsidian/``.
"""

from .store import LearningStore, load_store
from .feedback import record_feedback
from .ratings import rate_edit, rating_summary
from .dislikes import remember_dislike, active_rules_for
from .apply import priors_for_config, attach_learning_to_report, apply_priors_to_config
from .daily import run_daily, due_for_daily

__all__ = [
    "LearningStore",
    "load_store",
    "record_feedback",
    "rate_edit",
    "rating_summary",
    "remember_dislike",
    "active_rules_for",
    "priors_for_config",
    "attach_learning_to_report",
    "apply_priors_to_config",
    "run_daily",
    "due_for_daily",
]
