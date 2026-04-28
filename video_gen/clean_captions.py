"""Strip text-overlay and watermark references from SALMONN captions.

Used to prevent T2V models from trying to render garbled pseudo-text
at the positions described in the caption.

Strategy:
1. Remove anything in quotes (transcribed on-screen text)
2. Drop sentences mentioning: text, watermark, subtitle, overlay, logo,
   banner, caption, title card, onscreen, marquee, lower third, chyron
3. Drop sentences about things being "displayed", "shown", "written",
   "reads", "appears at the bottom/top/corner" (usually text descriptions)
4. Clean up double spaces and orphan punctuation
"""

import re
from typing import Iterable


# Match ONLY double-quoted strings. Skip single quotes entirely because SALMONN
# uses apostrophes for possessives ("person's"), which collide with quoted text.
# Sentence-level filtering handles any remaining quoted text fragments.
_QUOTE_PAT = re.compile(
    r'"[^"]*"'                      # straight double "..."
    r"|\u201c[^\u201d]*\u201d"      # curly double "..."
)

_TRIGGER_WORDS = [
    r"text\s+overlay",
    r"text",           # matched as standalone word via outer \b
    r"watermarks?",
    r"subtitles?",
    r"captions?",
    r"overlays?",
    r"logos?",
    r"banners?",
    r"titles?\s+cards?",
    r"onscreen", r"on-screen",
    r"marquees?",
    r"lower\s+thirds?",
    r"chyrons?",
    r"news\s+tickers?",
    r"copyright\s+notices?",
    r"credits?\s+(?:for|line|roll)",
    r"hashtags?",
    r"usernames?",
    r"emoji",
    r"sticker",
    r"graphic\s+text",
]
_DISPLAY_VERBS = [
    r"reads?\s*:?", r"displayed", r"written", r"typed",
    r"spell(?:s|ed|ing)?\s+out",
]
_POSITIONAL_PHRASES = [
    r"(?:appears?|visible|seen|placed|positioned|located|shown)\s+"
    r"(?:at|in|on)\s+the\s+"
    r"(?:top|bottom|left|right|center|middle|upper|lower|"
    r"corner|side|edge|background|foreground|screen|frame|image|video)",
]

_TRIGGER_PAT = re.compile(
    r"\b(?:" + "|".join(_TRIGGER_WORDS) + r")\b", re.IGNORECASE
)
_VERB_PAT = re.compile(
    r"\b(?:" + "|".join(_DISPLAY_VERBS) + r")\b", re.IGNORECASE
)
_POSITIONAL_PAT = re.compile(
    r"(?:" + "|".join(_POSITIONAL_PHRASES) + r")", re.IGNORECASE
)

# Sentence splitter — simple but good enough for SALMONN's clean English output
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _sentence_should_drop(sentence: str) -> bool:
    if _TRIGGER_PAT.search(sentence):
        return True
    if _POSITIONAL_PAT.search(sentence):
        return True
    # Verb patterns only drop if combined with 'the' or 'a' (signals text object)
    if _VERB_PAT.search(sentence) and re.search(r"\b(?:the|a|an)\b", sentence, re.I):
        return True
    return False


def clean_caption(caption: str) -> str:
    """Strip text-overlay + watermark references from a SALMONN caption."""
    # 1. Kill quoted text
    text = _QUOTE_PAT.sub("", caption)

    # 2. Split into sentences, drop problematic ones
    sentences = _SENT_SPLIT.split(text.strip())
    kept = [s for s in sentences if not _sentence_should_drop(s)]

    # 3. Rejoin
    out = " ".join(kept)

    # 4. Cleanup: collapse whitespace, remove orphan punctuation
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"\s*,\s*,+", ",", out)
    out = out.strip(" ,.;:-")

    return out


def clean_captions_dict(captions: dict) -> dict:
    """Clean a {filename: {caption: str, ...}} dict, returning a new dict."""
    out = {}
    for fn, v in captions.items():
        if isinstance(v, dict) and "caption" in v:
            new_v = dict(v)
            new_v["caption_raw"] = v["caption"]
            new_v["caption"] = clean_caption(v["caption"])
            out[fn] = new_v
        else:
            out[fn] = v
    return out
