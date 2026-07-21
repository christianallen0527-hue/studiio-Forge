"""CLI — major learning subsystem.

  python -m autoedit.learning daily              # every day: top podcasts/TH/long/shorts
  python -m autoedit.learning study <youtube-url>
  python -m autoedit.learning rate <path> 16     # -1 bad … 20 perfect
  python -m autoedit.learning dislike "shaky tails" --situation sponsor
  python -m autoedit.learning feedback not_okay "…"
  python -m autoedit.learning show
  python -m autoedit.learning seed-defaults
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AUTOEDITING FORGE — editorial learning brain")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("daily", help="Study top podcasts / talking heads / long-form / shorts")
    d.add_argument("--category", action="append", default=[],
                   help="Limit to category id (repeatable)")
    d.add_argument("--per-category", type=int, default=3)
    d.add_argument("--with-samples", action="store_true",
                   help="Also download short low-res samples (slower)")

    s = sub.add_parser("study", help="Study one public YouTube URL")
    s.add_argument("url")
    s.add_argument("--label", action="append", default=[])
    s.add_argument("--notes", default="")
    s.add_argument("--no-sample", action="store_true")

    sl = sub.add_parser("study-local", help="Study a local reference edit")
    sl.add_argument("path")
    sl.add_argument("--label", action="append", default=[])
    sl.add_argument("--notes", default="")

    r = sub.add_parser("rate", help="Rate an edit -1 (bad) … 20 (perfect)")
    r.add_argument("path")
    r.add_argument("score", type=float)
    r.add_argument("--category", default="general")
    r.add_argument("--notes", default="")
    r.add_argument("--job", default="")

    dl = sub.add_parser("dislike", help="Never-again memory (contextual)")
    dl.add_argument("text")
    dl.add_argument("--situation", default="general",
                    help="sponsor | podcast | talking_head | long_form | shorts | general")

    f = sub.add_parser("feedback", help="wanted / not_okay taste feedback")
    f.add_argument("sentiment", choices=["wanted", "not_okay", "good", "bad", "eww"])
    f.add_argument("text")
    f.add_argument("--subject", default="general")
    f.add_argument("--tag", action="append", default=[])

    sub.add_parser("show", help="Print priors, ratings, rules, daily status")
    sub.add_parser("seed-defaults", help="Seed store + dislike rules from studio taste")
    c = sub.add_parser("compare", help="Compare an edit to learned priors")
    c.add_argument("path")
    c.add_argument("--situation", default="general")

    args = p.parse_args(argv)
    log = lambda m="": print(m, flush=True)

    if args.cmd == "daily":
        from .daily import run_daily
        cats = args.category or None
        print(json.dumps(run_daily(
            categories=cats, per_category=args.per_category,
            download_sample=args.with_samples, log=log), indent=2)[:5000])
        return 0

    if args.cmd == "study":
        from .youtube_study import study_youtube
        print(json.dumps(study_youtube(
            args.url, labels=args.label, notes=args.notes,
            download_sample=not args.no_sample, log=log), indent=2)[:4000])
        return 0

    if args.cmd == "study-local":
        from .youtube_study import study_local
        print(json.dumps(study_local(
            args.path, labels=args.label, notes=args.notes, log=log), indent=2))
        return 0

    if args.cmd == "rate":
        from .ratings import rate_edit, rating_summary
        rate_edit(args.path, args.score, category=args.category,
                  notes=args.notes, job_id=args.job, log=log)
        print(json.dumps(rating_summary(), indent=2))
        return 0

    if args.cmd == "dislike":
        from .dislikes import remember_dislike, active_rules_for
        remember_dislike(args.text, situation=args.situation, log=log)
        print(json.dumps(active_rules_for(args.situation), indent=2))
        return 0

    if args.cmd == "feedback":
        from .feedback import record_feedback
        # also mirror not_okay into dislike memory
        ev = record_feedback(args.text, sentiment=args.sentiment,
                             subject=args.subject, tags=args.tag, log=log)
        if ev["sentiment"] == "not_okay":
            from .dislikes import remember_dislike
            remember_dislike(args.text, situation=args.subject, source="feedback", log=log)
        print(json.dumps(ev, indent=2))
        return 0

    if args.cmd == "show":
        from .store import load_store, recompute_priors
        from .ratings import rating_summary
        from .daily import due_for_daily
        store = load_store()
        recompute_priors(store)
        store.save()
        print(json.dumps({
            "stats": store.stats,
            "priors": store.priors,
            "category_priors": store.category_priors,
            "active_rules": store.active_rules,
            "ratings": rating_summary(store),
            "daily_due_today": due_for_daily(store),
            "references": len(store.references),
            "dislikes": len(store.dislikes),
        }, indent=2)[:8000])
        return 0

    if args.cmd == "seed-defaults":
        return _seed(log)

    if args.cmd == "compare":
        from .apply import compare_edit_to_priors
        from .dislikes import violations_for_report
        rep = compare_edit_to_priors(args.path, log=log)
        # wrap as issues list for violation helper
        fake = {"issues": [{"code": "shake"}] if any("shak" in i.lower() for i in rep.get("issues", [])) else []}
        rep["never_again_hits"] = violations_for_report(
            {"issues": _codes_from_compare(rep)}, situation=args.situation)
        print(json.dumps(rep, indent=2))
        return 0

    return 2


def _codes_from_compare(rep: dict) -> list[dict]:
    codes = []
    for issue in rep.get("issues") or []:
        low = issue.lower()
        if "shak" in low:
            codes.append({"code": "shake"})
        if "dated" in low or "card" in low:
            codes.append({"code": "dated_card"})
        if "chopp" in low:
            codes.append({"code": "jump_cut"})
    return codes


def _seed(log) -> int:
    from .store import load_store, recompute_priors
    from .dislikes import remember_dislike
    from .feedback import record_feedback

    store = load_store()
    recompute_priors(store)
    store.save()
    log(f"seeded {store.path()}")

    dislikes = [
        ("sponsor", "shaky last clips — stabilize, never deliver wobble"),
        ("sponsor", "music hard-loop seam in the middle — must be seamless"),
        ("sponsor", "typing click SFX — remove, clean music only"),
        ("sponsor", "80s navy gold dated cards — modern kinetic over house only"),
        ("general", "jump cuts feel bad — prefer smooth dissolves"),
    ]
    for sit, text in dislikes:
        if any(d.get("text") == text for d in store.dislikes):
            continue
        remember_dislike(text, situation=sit, source="seed", log=log)

    wanted = [
        ("sponsor", "original first-ad upbeat clean music only"),
        ("sponsor", "modern kinetic type over live house footage"),
        ("general", "smooth dissolves and seamless music beds"),
    ]
    store = load_store()
    for subj, text in wanted:
        if any(fb.get("text") == text for fb in store.feedback):
            continue
        record_feedback(text, sentiment="wanted", subject=subj, log=log)

    log("Obsidian: context_docs/obsidian/Editorial Learning.md + Never Again.md")
    log("Schedule daily: python -m autoedit.learning daily")
    return 0


if __name__ == "__main__":
    sys.exit(main())
