"""Make a podcast script from the command line (the web app runs the same steps):

  python -m podcast_agent --topic "How UPI payments work" --lang hi --description "for class 8 students"
"""
import argparse
from pathlib import Path

from .config import RUNS
from .episode import new_episode
from .languages import CODE_MIX, LANGS
from .pipeline import run_all


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic", required=True)
    ap.add_argument("--description", default="", help="free text: audience level, tone, angle")
    ap.add_argument("--lang", default="en", choices=LANGS)
    ap.add_argument("--speakers", type=int, default=2)
    ap.add_argument("--minutes", type=float, default=12)
    ap.add_argument("--code-mix", default="medium", choices=CODE_MIX)
    ap.add_argument("--max-research-steps", type=int, default=20)
    ap.add_argument("--max-revisions", type=int, default=2)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--out", type=Path, default=RUNS)
    a = ap.parse_args()
    ep = new_episode(a.topic, a.description, a.lang, a.speakers, a.minutes, a.code_mix, a.seed, a.out)
    print(f"run dir: {ep['dir']}", flush=True)
    run_all(ep, a.max_research_steps, a.max_revisions)


if __name__ == "__main__":
    main()
