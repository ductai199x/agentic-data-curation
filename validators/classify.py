"""Shared classification logic for JoyCaption and VLM outputs.

This module reads REJECT_KEYWORDS from the generator config. All validators
import from here instead of maintaining their own keyword lists.

Usage:
    from configs import load_config
    from validators.classify import classify_caption

    config = load_config("configs/grok.py")
    result = classify_caption(caption_text, config)
"""

import re


# Booru tag prompt — most reliable for content filtering
CAPTION_PROMPT = "Write a list of Booru-like tags for this image."


def _word_match(keyword: str, text: str) -> bool:
    """Check if keyword appears as a whole word (not substring) in text."""
    return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))


def classify_caption(caption: str, config) -> dict:
    """Classify image from its JoyCaption output.

    Uses two-tier keyword matching from config:
    - REJECT_KEYWORDS: always reject (unambiguous non-image content)
    - TEXT_PAIRED_KEYWORDS: only reject when co-occurring with TEXT_INDICATORS

    Returns dict with keys: should_reject, reject_signals, caption.
    """
    reject_keywords = getattr(config, "REJECT_KEYWORDS", [])
    text_paired_keywords = getattr(config, "TEXT_PAIRED_KEYWORDS", [])
    text_indicators = getattr(config, "TEXT_INDICATORS", [])

    caption_lower = caption.lower()

    # Check strong reject keywords
    reject_signals = [kw for kw in reject_keywords if _word_match(kw, caption_lower)]

    # Check text-paired keywords — only reject if text indicators also present
    paired_matches = [kw for kw in text_paired_keywords if _word_match(kw, caption_lower)]
    if paired_matches:
        has_text_indicator = any(
            _word_match(ti, caption_lower) for ti in text_indicators
        )
        if has_text_indicator:
            reject_signals.extend(paired_matches)

    return {
        "should_reject": len(reject_signals) > 0,
        "reject_signals": reject_signals,
        "caption": caption,
    }


def check_blocked_content(tags: str | list, config) -> list[str]:
    """Check if booru tags contain content the generator can't produce.

    Returns list of matched blocked keywords (empty = clean).
    """
    blocked_tags = getattr(config, "BLOCKED_CONTENT_TAGS", [])
    tag_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
    tag_lower = tag_str.lower()
    return [kw for kw in blocked_tags if kw in tag_lower]


def matches_known_ratio(w: int, h: int, config, tolerance: float | None = None) -> str | None:
    """Check if image matches any known generator aspect ratio.

    Returns matched ratio string (e.g. "16:9") or None.
    """
    known_ratios = getattr(config, "KNOWN_ASPECT_RATIOS", [])
    tol = tolerance or getattr(config, "ASPECT_RATIO_TOLERANCE", 0.05)
    if not known_ratios or w == 0 or h == 0:
        return None
    img_ratio = w / h
    for rw, rh in known_ratios:
        expected = rw / rh
        if abs(img_ratio - expected) / expected <= tol:
            return f"{rw}:{rh}"
    return None
