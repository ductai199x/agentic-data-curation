"""ChatGPT (GPT-Image-1 / GPT-Image-1.5) — generator configuration.

OpenAI's native image generation models integrated into ChatGPT.
- GPT-Image-1: Released April 2025, autoregressive (GPT-4o based)
- GPT-Image-1.5: Released December 2025, GPT-5 based, 4x faster

Outputs include C2PA metadata (but stripped by CDNs/social media).
Only 3 aspect ratios supported via API: 1:1, 3:2, 2:3.
"""

# === Generator identity ===
NAME = "chatgpt"
DISPLAY_NAME = "ChatGPT (GPT-Image-1 / 1.5)"

# === Image characteristics ===
EXPECTED_FORMATS = ["JPEG", "PNG", "WEBP"]
MIN_PIXELS = 800_000     # Smallest output is 1024x1024 (1,048,576 px). Give margin for CDN recompression.
MAX_PIXELS = 30_000_000  # v1.5 on Civitai shows up to 4096x6144 (~25M px)

# JPEG quantization: Civitai CDN serves as JPEG, quality varies
MAX_AVG_QUANTIZATION = 40.0

# Known aspect ratios from OpenAI API docs
# API only supports: 1:1, 3:2, 2:3
# Civitai on-site gen may produce at non-standard ratios due to platform settings
KNOWN_ASPECT_RATIOS = [
    (1, 1),       # 1:1  — 1024x1024
    (3, 2),       # 3:2  — 1536x1024
    (2, 3),       # 2:3  — 1024x1536
]
ASPECT_RATIO_TOLERANCE = 0.05  # 5% tolerance for rounding

# EXIF: presence of camera tags = NOT GPT-Image output
CAMERA_EXIF_TAGS = [
    "Make", "Model", "ExposureTime", "FNumber",
    "ISOSpeedRatings", "FocalLength",
]

# === Scraping: Civitai ===
# Model: "OpenAI's GPT-image-1" (model_id=1532032)
# On-site generation only — tool_id is unreliable (anyone can upload with any tags)
CIVITAI_MODEL_VERSIONS = [
    (1532032, 1733399),   # GPT-Image-1 (4o Image Gen 1) — ~14K on-site images
    (1532032, 2512167),   # GPT-Image-1.5 — ~4.1K on-site images
]
CIVITAI_TOOL_ID = None  # DO NOT USE — unreliable provenance

# === Scraping: Higgsfield ===
# Very small volume but good provenance
HIGGSFIELD_API_BASE = "https://fnf.higgsfield.ai/publications/community"
HIGGSFIELD_MODELS = ["openai_hazel", "text2image_gpt"]
HIGGSFIELD_COOKIES_PATH = "data/cookies-higgsfield.txt"
HIGGSFIELD_PAGE_SIZE = 50

# === Scraping: Reddit ===
# Reddit is VERY risky for GPT-Image because:
# - "ChatGPT" flairs don't distinguish GPT-Image-1 from DALL-E 3
# - No subreddit has reliable GPT-Image-specific flairs
# - Skip unless we need supplemental volume AND can verify provenance
REDDIT_SUBREDDITS = []  # Intentionally empty — provenance too uncertain

# === Scraping: Twitter/X ===
# No official bot account. @ChatGPTapp doesn't post user-requested generations.
# Dead end for this generator.
TWITTER_BOT_USERNAME = None

# === Safety / provenance ===
# GPT-Image hard-blocks: nudity, sexual content, extreme violence, CSAM, deepfake sexual
# Public figures allowed since March 2025 with restrictions
BLOCKED_CONTENT_TAGS = [
    "penis", "vagina", "vulva", "genitals", "testicle",
    "labia", "clitoris", "phallus",
    "gore", "blood", "severed", "dismembered",
]

# === Content classification (JoyCaption / VLM) ===
REJECT_KEYWORDS = [
    # Non-photorealistic content (body text matches)
    "illustration", "cartoon", "anime", "cgi", "comic",
    "line drawing", "sketch", "digital art", "digital painting",
    "3d render", "pixel art", "vector art", "watercolor",
    "oil painting", "pencil drawing", "manga",
    # Screenshots / UI
    "screenshot", "user interface", "app interface", "chat interface",
    "settings page", "settings menu", "status bar",
    "navigation bar", "toolbar", "menu bar", "dialog box",
    "browser window", "browser tab", "address bar", "url bar",
    "home screen", "lock screen", "search bar",
    "file manager", "task manager", "control panel",
    # Maps / satellite UI
    "google maps", "google earth", "street view", "map pin",
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
    # Technical / error
    "error message", "error screen", "loading screen",
    "code snippet", "terminal", "command line",
    "source code", "stack trace",
    "api response", "json output", "xml output",
    # Unambiguous data/document content
    "spreadsheet", "powerpoint", "presentation slide",
    # Leaderboards / rankings
    "leaderboard", "ranking", "scoreboard",
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
