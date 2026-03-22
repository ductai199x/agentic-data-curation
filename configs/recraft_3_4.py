"""Recraft V3 / V4 — generator configuration.

Recraft's proprietary image generation models.
- Recraft V3: Released 2024
- Recraft V4: Released 2025 (raster + pro variants)
- Recraft V4 Pro Raster: Up to 4MP output

Architecture: Proprietary (not publicly disclosed).
Community gallery at https://www.recraft.ai with public API.
Strict NSFW filter — almost all content is safe.
"""

# === Generator identity ===
NAME = "recraft_3_4"
DISPLAY_NAME = "Recraft V3 / V4"

# === Image characteristics ===
EXPECTED_FORMATS = ["JPEG", "PNG", "WEBP"]
MIN_PIXELS = 500_000      # Smallest likely: ~720x720
MAX_PIXELS = 5_000_000    # V4 Pro goes up to 4MP. Give margin.

# JPEG quantization: imgproxy CDN serves quality 100 by default
MAX_AVG_QUANTIZATION = 40.0

# Known aspect ratios from Recraft UI
KNOWN_ASPECT_RATIOS = [
    (1, 1),       # 1:1  — 1024x1024
    (4, 3),       # 4:3
    (3, 4),       # 3:4
    (3, 2),       # 3:2
    (2, 3),       # 2:3
    (16, 9),      # 16:9
    (9, 16),      # 9:16
    (2, 1),       # 2:1
    (1, 2),       # 1:2
    (5, 4),       # 5:4
    (4, 5),       # 4:5
    (7, 5),       # 7:5
    (5, 7),       # 5:7
    (5, 3),       # 5:3
    (3, 5),       # 3:5
]
ASPECT_RATIO_TOLERANCE = 0.05  # 5% tolerance

# EXIF: presence of camera tags = NOT Recraft output
CAMERA_EXIF_TAGS = [
    "Make", "Model", "ExposureTime", "FNumber",
    "ISOSpeedRatings", "FocalLength",
]

# === Scraping: Civitai ===
# No Civitai presence for Recraft
CIVITAI_MODEL_VERSIONS = []
CIVITAI_TOOL_ID = None

# === Scraping: Recraft ===
# Community gallery API: GET https://api.recraft.ai/images/community
# No auth required. 1,000 item cap per query combo.
RECRAFT_API_DELAY = (1.0, 2.0)
RECRAFT_DOWNLOAD_DELAY = (0.5, 1.0)
RECRAFT_DOWNLOAD_WORKERS = 4

# === Scraping: Reddit ===
REDDIT_SUBREDDITS = []
REDDIT_SEARCH_QUERIES = []

# === Scraping: Twitter/X ===
TWITTER_BOT_USERNAME = None

# === Safety / provenance ===
# Recraft has strict NSFW filter — these tags are provenance signals
BLOCKED_CONTENT_TAGS = [
    "penis", "vagina", "vulva", "genitals", "testicle",
    "labia", "clitoris", "phallus",
    "gore", "blood", "severed", "dismembered",
    "nude", "naked", "topless", "nipple",
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
