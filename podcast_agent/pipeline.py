"""The order the agents run in: plan, research, then write every segment."""
from .agents.producer import produce
from .agents.researcher import research
from .agents.writer import write_segment
from .episode import update_stats


def write_all(ep, max_revisions=2, only_missing=False):
    for i, seg in enumerate(ep["plan"]["segments"]):
        if not (only_missing and seg.get("turns")):
            write_segment(ep, i, max_revisions)
    update_stats(ep)


def run_all(ep, max_research_steps=20, max_revisions=2):
    """Everything still missing: plan -> research -> unwritten segments."""
    if not ep["plan"]:
        produce(ep)
    if not ep["facts"]:
        research(ep, max_research_steps)
    write_all(ep, max_revisions, only_missing=True)
