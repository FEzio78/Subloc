"""Compare our subtitles against reference subtitles (e.g. official ones built into the file).

    .venv/Scripts/python tools/compare_subs.py VIDEO --ref-track 1 [--samples 15]

Reports:
- coverage: share of reference lines that overlap one of ours in time (did we catch the speech?)
- extra:    share of our lines that overlap no reference line (hallucinations, or lines the
            reference skipped on purpose: songs, background chatter)
- samples:  reference text next to ours, to judge meaning by eye
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subloc.media import read_subtitles
from subloc.models import Project
from subloc.pipeline import project_path
from subloc.subparse import parse


def overlap(a, b) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("video", type=Path)
    p.add_argument("--ref-track", type=int, default=1, help="built-in subtitle track to compare against (1 = first)")
    p.add_argument("--samples", type=int, default=15)
    a = p.parse_args()

    proj = Project.load(project_path(a.video.resolve()))
    ours = proj.cues
    ref = [c for c in parse(read_subtitles(a.video, a.ref_track - 1)) if c.kind == "dialogue"]

    covered = [r for r in ref if any(overlap(r, o) > 0.2 for o in ours)]
    extra = [o for o in ours if not any(overlap(o, r) > 0.2 for r in ref)]
    print(f"reference dialogue lines: {len(ref)}   ours: {len(ours)}")
    print(f"coverage: {len(covered) / max(len(ref), 1):.0%} of reference lines overlap one of ours")
    print(f"extra:    {len(extra) / max(len(ours), 1):.0%} of our lines overlap no reference line")
    print("\nsome of our lines with no reference line:")
    for o in extra[:10]:
        print(f"  {o.start / 60:5.1f}m  {o.text[:60]}  →  {o.translation or ''}")

    print("\nside by side (reference | ours):")
    step = max(1, len(ref) // a.samples)
    for r in ref[::step][: a.samples]:
        mine = [o for o in ours if overlap(r, o) > 0.2]
        print(f"\n  {r.start / 60:5.1f}m  REF:  {r.text}")
        for o in mine:
            print(f"          OURS: {o.text}   →  {o.translation or ''}")


if __name__ == "__main__":
    main()
