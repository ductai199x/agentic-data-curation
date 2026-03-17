"""Seedream 4.0 / 4.5 / 5.0 Lite — generator configuration.

ByteDance's diffusion transformer (DiT) with Mixture-of-Experts (MoE).
- Seedream 4.0: Released September 9, 2025
- Seedream 4.5: Released December 3, 2025
- Seedream 5.0 Lite: Released February 24, 2026

Supports 1K-4K resolution, extremely flexible aspect ratios (1/16 to 16:1).
"""

# === Generator identity ===
NAME = "seedream4"
DISPLAY_NAME = "Seedream 4.0 / 4.5 (ByteDance)"

# === Image characteristics ===
EXPECTED_FORMATS = ["JPEG", "PNG", "WEBP"]
MIN_PIXELS = 500_000      # Smallest likely: ~720x720. Give margin.
MAX_PIXELS = 20_000_000   # 4K mode: up to 4096x4096 (~16.8M px). Give margin.

# JPEG quantization: Civitai CDN serves as JPEG, quality varies
MAX_AVG_QUANTIZATION = 40.0

# Extremely flexible aspect ratios (1/16 to 16:1)
# Common presets from API docs + observed on Civitai/Higgsfield
KNOWN_ASPECT_RATIOS = [
    (1, 1),       # 1:1  — 1024x1024, 2048x2048
    (16, 9),      # 16:9 — 1920x1080, 2560x1440
    (9, 16),      # 9:16 — 1080x1920, 1440x2560
    (3, 2),       # 3:2  — 1536x1024
    (2, 3),       # 2:3  — 1024x1536
    (4, 3),       # 4:3  — 1024x768, 2048x1536
    (3, 4),       # 3:4  — 768x1024, 1536x2048
    (21, 9),      # 21:9 — ultrawide
    (9, 21),      # 9:21
    (3, 1),       # 3:1
    (1, 3),       # 1:3
    (4, 1),       # 4:1
    (1, 4),       # 1:4
    (5, 4),       # 5:4
    (4, 5),       # 4:5
    (7, 4),       # 7:4
    (4, 7),       # 4:7
]
ASPECT_RATIO_TOLERANCE = 0.08  # 8% tolerance — very flexible generator

# EXIF: presence of camera tags = NOT Seedream output
CAMERA_EXIF_TAGS = [
    "Make", "Model", "ExposureTime", "FNumber",
    "ISOSpeedRatings", "FocalLength",
]

# === Scraping: Civitai ===
# Model: "Seedream" (model_id=1951069)
# On-site generation only — no tool_id
CIVITAI_MODEL_VERSIONS = [
    (1951069, 2208278),   # Seedream 4.0 — ~2,237 on-site images
    (1951069, 2470991),   # Seedream 4.5 — ~1,201 on-site images
    (1951069, 2720141),   # Seedream 5.0 Lite — ~69 on-site images
]
CIVITAI_TOOL_ID = None  # No tool_id exists for Seedream

# === Scraping: Higgsfield ===
HIGGSFIELD_API_BASE = "https://fnf.higgsfield.ai/publications/community"
HIGGSFIELD_MODELS = ["seedream", "seedream_v4_5", "seedream_v5_lite"]
HIGGSFIELD_COOKIES_PATH = "data/cookies-higgsfield.txt"
HIGGSFIELD_PAGE_SIZE = 50

# === Scraping: Reddit ===
# Seedream has virtually NO Reddit presence — skip entirely.
REDDIT_SUBREDDITS = []
REDDIT_SEARCH_QUERIES = []

# === Scraping: Twitter/X ===
# No official bot account.
TWITTER_BOT_USERNAME = None

# === Safety / provenance ===
# Seedream blocks: NSFW (99%), violence/gore (95%), political figures (95%)
# Higgsfield may bypass some filters — watch for NSFW content
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

# === Rate limiting ===
REQUEST_DELAY = (1.0, 5.0)
CIVITAI_API_DELAY = (3.0, 6.0)
CIVITAI_DOWNLOAD_DELAY = (0.5, 1.5)
CIVITAI_DOWNLOAD_WORKERS = 4  # Concurrent CDN download workers
HIGGSFIELD_DELAY = (3.0, 7.0)
