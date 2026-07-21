"""Turn learned priors into config knobs + review recommendations."""

from __future__ import annotations

from .store import LearningStore, load_store, recompute_priors


def priors_for_config(store: LearningStore | None = None) -> dict:
    """Subset of priors safe to map onto Config / finish / switch knobs."""
    store = store or load_store()
    if not store.priors:
        recompute_priors(store)
    p = store.priors
    conf = float(p.get("confidence") or 0)
    # Only nudge knobs once we have a little evidence
    out = {
        "confidence": conf,
        "style_tags": list(p.get("style_tags") or []),
        "recommendations": [],
    }
    if conf < 0.2:
        out["recommendations"].append(
            "Learning store is young — study more public YouTube refs "
            "(`python -m autoedit.learning study <url>`) and keep recording feedback."
        )
        return out

    out["suggested"] = {
        "min_shot_sec": p.get("min_shot_sec"),
        "speech_transition_sec": p.get("speech_transition_sec"),
        "transition_sec": p.get("transition_sec"),
        "fade_sec": p.get("fade_sec"),
    }
    if p.get("prefer_smooth_dissolves"):
        out["recommendations"].append(
            "Priors favor smooth dissolves — keep speech_transition_sec ≥ 0.4."
        )
    if p.get("forbid_shaky_tails"):
        out["recommendations"].append(
            "Priors forbid shaky tails — stabilize or re-cut final clips."
        )
    if p.get("music_must_be_seamless"):
        out["recommendations"].append(
            "Priors require seamless music beds (crossfade loops, no hard restarts)."
        )
    if p.get("forbid_dated_title_cards"):
        out["recommendations"].append(
            "Priors reject dated navy/gold cards — use modern kinetic type over live footage."
        )
    if p.get("forbid_click_sfx"):
        out["recommendations"].append(
            "Priors reject click/typing SFX — original clean music only for HPM-style spots."
        )
    return out


def apply_priors_to_config(cfg, store: LearningStore | None = None, log=print):
    """Gently nudge a Config instance from learned priors (non-destructive)."""
    store = store or load_store()
    recompute_priors(store)
    p = store.priors
    conf = float(p.get("confidence") or 0)
    if conf < 0.25:
        log("  learning: confidence low — leaving config knobs unchanged")
        return cfg

    # Only raise smoothness / min shot — never make edits harsher than the project asked
    try:
        if p.get("prefer_smooth_dissolves"):
            cfg.speech_transition_sec = max(
                float(cfg.speech_transition_sec), float(p.get("speech_transition_sec") or 0.4))
            cfg.transition_sec = max(
                float(cfg.transition_sec), float(p.get("transition_sec") or 0.6))
            cfg.fade_sec = max(float(cfg.fade_sec), float(p.get("fade_sec") or 0.75))
        if p.get("min_shot_sec"):
            cfg.min_shot_sec = max(float(cfg.min_shot_sec), float(p["min_shot_sec"]) * 0.9)
        store.stats["apply_count"] = int(store.stats.get("apply_count") or 0) + 1
        store.save()
        log(f"  learning: applied priors (confidence={conf})")
    except Exception as e:  # noqa: BLE001
        log(f"  learning: could not apply priors ({e})")
    return cfg


def attach_learning_to_report(report: dict, store: LearningStore | None = None) -> dict:
    """Embed learning snapshot into review.json / results dict."""
    store = store or load_store()
    info = priors_for_config(store)
    from .daily import due_for_daily
    from .dislikes import active_rules_for
    from .ratings import rating_summary
    report = dict(report or {})
    report["learning"] = {
        "confidence": info.get("confidence"),
        "stats": store.stats,
        "priors": store.priors,
        "category_priors": store.category_priors,
        "recommendations": info.get("recommendations") or [],
        "suggested_knobs": info.get("suggested"),
        "never_again_rules": active_rules_for("general"),
        "ratings": rating_summary(store),
        "daily_due_today": due_for_daily(store),
        "rating_scale": {"min": -1, "max": 20, "target": store.priors.get("rating_target", 18)},
    }
    return report


def compare_edit_to_priors(path: str, store: LearningStore | None = None, log=print) -> dict:
    """Score a finished edit against learned priors (for review-before-show)."""
    from .features import extract_features
    store = store or load_store()
    feat = extract_features(path, log=log)
    p = store.priors or {}
    issues = []
    if p.get("forbid_shaky_tails") and (feat.get("shake_score") or 0) > 12:
        issues.append("Edit tail is shakier than learned 'good' refs.")
    if p.get("forbid_dated_title_cards") and (feat.get("dark_card_ratio") or 0) >= 0.35:
        issues.append("Edit still contains dated flat-card frames.")
    if p.get("prefer_smooth_dissolves") and feat.get("median_shot_sec") and feat["median_shot_sec"] < 1.2:
        issues.append("Pacing is choppier than learned smooth-edit priors.")
    return {
        "features": feat,
        "issues": issues,
        "verdict": "fail" if issues else "pass",
        "confidence": p.get("confidence"),
    }
