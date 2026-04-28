"""Higgsfield Soul 2.0 and variants — generator configuration.

Higgsfield's proprietary image generation model.
- Soul v1 (text2image_soul): Original model, largest gallery (31,784 posts)
- Soul v2 (text2image_soul_v2): Newer version (2,370 posts)
- Soul Cinematic (soul_cinematic): Cinematic variant with color presets (545 posts)
- AI Influencer (ai_influencer): Portrait-focused variant (1,001 posts)

All served as PNGs on CloudFront CDN. No Civitai presence.
"""

# === Generator identity ===
NAME = "soul2"
DISPLAY_NAME = "Higgsfield Soul 2.0"

# === Image characteristics ===
EXPECTED_FORMATS = ["JPEG", "PNG", "WEBP"]
MIN_PIXELS = 500_000      # Smallest observed: ~960x1696
MAX_PIXELS = 25_000_000   # Cinematic 4K mode: up to 6336x2688

# JPEG quantization: Higgsfield serves PNGs, but some JPEG from ai_influencer
MAX_AVG_QUANTIZATION = 40.0

# Observed resolutions across all variants
KNOWN_ASPECT_RATIOS = [
    (1, 1),       # 1:1  — 1536x1536
    (16, 9),      # 16:9 — 2048x1152, 2752x1536
    (9, 16),      # 9:16 — 1152x2048, 1536x2752
    (3, 2),       # 3:2  — 1536x1024, 2048x1344
    (2, 3),       # 2:3  — 1024x1536, 1344x2048
    (4, 3),       # 4:3  — 1536x1152, 2048x1536
    (3, 4),       # 3:4  — 1152x1536, 1536x2048
    (21, 9),      # 21:9 — 2560x1080 (cinematic)
    (9, 21),      # 9:21
    (5, 4),       # 5:4
    (4, 5),       # 4:5
    (7, 4),       # 7:4  — 1632x1088 (cinematic)
    (4, 7),       # 4:7
]
ASPECT_RATIO_TOLERANCE = 0.08  # 8% tolerance

# EXIF: presence of camera tags = NOT Soul output
CAMERA_EXIF_TAGS = [
    "Make", "Model", "ExposureTime", "FNumber",
    "ISOSpeedRatings", "FocalLength",
]

# === Scraping: Civitai ===
# Soul is NOT on Civitai — Higgsfield-only model
CIVITAI_MODEL_VERSIONS = []
CIVITAI_TOOL_ID = None

# === Scraping: Higgsfield ===
HIGGSFIELD_API_BASE = "https://fnf.higgsfield.ai/publications/community"
HIGGSFIELD_MODELS = ["soul_cinematic", "ai_influencer", "text2image_soul_v2", "text2image_soul"]
HIGGSFIELD_COOKIES_PATH = None  # Public API, no cookies needed
HIGGSFIELD_PAGE_SIZE = 50

# === Scraping: Reddit ===
REDDIT_SUBREDDITS = []
REDDIT_SEARCH_QUERIES = []

# === Scraping: Twitter/X ===
TWITTER_BOT_USERNAME = None

# === Safety / provenance ===
# Higgsfield applies content moderation but some NSFW gets through
BLOCKED_CONTENT_TAGS = [
    "penis", "vagina", "vulva", "genitals", "testicle",
    "labia", "clitoris", "phallus",
    "gore", "blood", "severed", "dismembered",
]

# === Content classification (JoyCaption / VLM) ===
REJECT_KEYWORDS = [
    # Explicit genital exposure only (other NSFW is acceptable)
    "penis", "vagina", "vulva", "genitals", "testicle",
    "labia", "clitoris", "phallus",
    "cum", "ejaculation", "cumshot",
    "penetration", "intercourse", "sex act",
    # Non-photorealistic content
    "illustration", "cartoon", "anime", "cgi", "comic",
    "line drawing", "sketch", "digital painting",
    "3d render", "pixel art", "vector art", "watercolor",
    "oil painting", "oil on canvas", "pencil drawing", "manga",
    # Screenshots / UI
    "screenshot", "user interface", "app interface", "chat interface",
    "settings page", "settings menu", "status bar",
    "navigation bar", "toolbar", "menu bar", "dialog box",
    "browser window", "browser tab", "address bar", "url bar",
    "home screen", "lock screen", "search bar",
    "file manager", "task manager", "control panel",
    # Maps / satellite UI
    "google maps", "google earth", "map pin",
    "satellite view", "map interface",
    # Social media UI
    "tweet", "retweet", "like button", "follow button",
    "comment section", "social media post",
    "verified badge", "instagram post", "tiktok",
    "facebook post", "reddit post",
    # Memes / text overlay
    "meme", "impact font", "text overlay",
    "top text", "bottom text", "demotivational",
    "reaction image", "rage comic",
    "speech bubble", "speech bubbles", "thought bubble",
    "word balloon", "dialogue bubble",
    # Technical / error
    "error message", "error screen", "loading screen",
    "code snippet", "terminal", "command line",
    "source code", "stack trace",
    "api response", "json output", "xml output",
    # Unambiguous data/document content
    "spreadsheet", "powerpoint", "presentation slide",
    # Leaderboards / rankings
    "leaderboard", "ranking", "scoreboard",
    # Graphic design / clipart
    "clipart", "clip art", "graphic design",
    "minimalistic art",
]

TEXT_PAIRED_KEYWORDS = [
    "table", "chart", "bar chart", "pie chart", "histogram",
    "scatter plot", "flow chart", "org chart", "gantt chart",
    "conversation", "chat bubble", "chat message", "text message",
    "notification", "login", "sign in", "sign up",
    "before and after", "side by side", "comparison",
    "collage", "grid of images", "photo grid",
    "infographic", "diagram", "schematic",
    "document", "receipt", "invoice", "certificate",
    "floor plan", "blueprint",
]

TEXT_INDICATORS = [
    "text", "font", "typed", "written", "caption",
    "heading", "title", "label", "header",
    "paragraph", "sentence", "words",
    "data", "numbers", "rows", "columns",
    "cells", "grid", "spreadsheet",
    "screenshot", "user interface", "browser",
]

# === Model version annotation mapping ===
# Maps Higgsfield model strings to metadata model_version values
HIGGSFIELD_MODEL_VERSION_MAP = {
    "text2image_soul": "soul_v1",
    "text2image_soul_v2": "soul_v2",
    "soul_cinematic": "soul_cinematic",
    "ai_influencer": "ai_influencer",
}

# === Rate limiting ===
REQUEST_DELAY = (1.0, 5.0)
HIGGSFIELD_DELAY = (3.0, 7.0)
