"""Midjourney v7 — generator configuration.

Midjourney generates images via a Discord bot (bot ID 936929561302675456)
in the official Midjourney Discord server (guild 662267976984297473).

Image types:
- Upscaled: single full-res image (content contains "Upscaled")
- Grid: 2x2 composite of 4 images (downloaded as-is, tagged "grid")

Version identification via component custom_ids (_v7_, _v8_, _v6r1_)
or --v flag in message content.

Auth: Discord user token from env var DISCORD_TOKEN.
"""

import os

# === Generator identity ===
NAME = "midjourney_v7"
DISPLAY_NAME = "Midjourney v7"

# === Image characteristics ===
EXPECTED_FORMATS = ["JPEG", "PNG", "WEBP"]
MIN_PIXELS = 500_000       # Midjourney min ~1024x1024 for upscales
MAX_PIXELS = 20_000_000    # 4x upscales can be 4096x4096

# JPEG quantization
MAX_AVG_QUANTIZATION = 40.0

# Midjourney supports very flexible aspect ratios (--ar flag)
# Common presets + any ratio between 1:2 and 2:1
KNOWN_ASPECT_RATIOS = [
    (1, 1),       # 1:1
    (16, 9),      # 16:9
    (9, 16),      # 9:16
    (3, 2),       # 3:2
    (2, 3),       # 2:3
    (4, 3),       # 4:3
    (3, 4),       # 3:4
    (4, 5),       # 4:5
    (5, 4),       # 5:4
    (7, 4),       # 7:4
    (4, 7),       # 4:7
    (21, 9),      # 21:9
    (9, 21),      # 9:21
    (2, 1),       # 2:1
    (1, 2),       # 1:2
    (3, 1),       # 3:1 (grids can be wider)
    (1, 3),       # 1:3
]
ASPECT_RATIO_TOLERANCE = 0.08  # 8% — flexible generator + grids

# EXIF: presence of camera tags = NOT Midjourney output
CAMERA_EXIF_TAGS = [
    "Make", "Model", "ExposureTime", "FNumber",
    "ISOSpeedRatings", "FocalLength",
]

# === Scraping: Discord ===
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
DISCORD_GUILD_ID = "662267976984297473"       # Midjourney official server
DISCORD_BOT_ID = "936929561302675456"         # Midjourney Bot
DISCORD_CHANNEL_PATTERN = r"^general-"        # Regex to match channel names
DISCORD_TARGET_VERSIONS = ["7", "8"]          # Only keep v7+ images
DISCORD_START_DATE = "2025-04-01"             # v7 launch date
DISCORD_API_DELAY = 3.0                       # Seconds between API calls
DISCORD_DOWNLOAD_DELAY = 0.5                  # Seconds between CDN downloads

# === Scraping: Civitai ===
# No Civitai on-site generation for Midjourney
CIVITAI_MODEL_VERSIONS = []
CIVITAI_TOOL_ID = None

# === Scraping: Reddit ===
REDDIT_SUBREDDITS = []
REDDIT_SEARCH_QUERIES = []

# === Scraping: Twitter/X ===
TWITTER_BOT_USERNAME = None

# === Safety / provenance ===
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
    "line drawing", "sketch", "digital painting", "digital drawing",
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
