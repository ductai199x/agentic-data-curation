"""FLUX.1 — generator configuration.

Black Forest Labs' Multimodal Diffusion Transformer (MMDiT).
- FLUX.1 [pro/dev/schnell]: Released August 1, 2024
- FLUX.1 Pro 1.1: Released October 2024
- FLUX.1 Pro 1.1 Ultra: Released November 2024
- FLUX.1 Redux: Released November 1, 2024 (image variation adapter)
- FLUX.1 Krea Dev: Released July 2025

Architecture: 12B param rectified flow transformer (MMDiT).
Dev/Schnell are open-weight; Pro is API-only.

Variants EXCLUDED from this config:
- FLUX.1 Fill (inpainting — mixes real content)
- FLUX.2 (separate generation family)
"""

# === Generator identity ===
NAME = "flux1"
DISPLAY_NAME = "FLUX.1 (Black Forest Labs)"

# === Image characteristics ===
EXPECTED_FORMATS = ["JPEG", "PNG", "WEBP"]
MIN_PIXELS = 200_000      # FLUX can go as low as 0.1MP but quality degrades
MAX_PIXELS = 5_000_000    # Ultra goes up to 4MP (2048x2048). Give margin.

# JPEG quantization: Civitai CDN serves as JPEG
MAX_AVG_QUANTIZATION = 40.0

# Known aspect ratios from fal.ai API docs + observed on Civitai
# FLUX dimensions must be multiples of 16
KNOWN_ASPECT_RATIOS = [
    (1, 1),       # 1:1  — 1024x1024, 2048x2048
    (16, 9),      # 16:9 — 1344x768, 1920x1080
    (9, 16),      # 9:16 — 768x1344, 1080x1920
    (3, 2),       # 3:2  — 1216x832
    (2, 3),       # 2:3  — 832x1216
    (4, 3),       # 4:3  — 1152x896, 1024x768
    (3, 4),       # 3:4  — 896x1152, 768x1024
    (21, 9),      # 21:9 — ultrawide
    (9, 21),      # 9:21
    (5, 4),       # 5:4  — ~1152x896 observed
    (4, 5),       # 4:5
    (7, 4),       # 7:4
    (4, 7),       # 4:7
    (2, 1),       # 2:1
    (1, 2),       # 1:2
]
ASPECT_RATIO_TOLERANCE = 0.06  # 6% tolerance — dimensions are multiples of 16

# EXIF: presence of camera tags = NOT FLUX output
CAMERA_EXIF_TAGS = [
    "Make", "Model", "ExposureTime", "FNumber",
    "ISOSpeedRatings", "FocalLength",
]

# === Scraping: Civitai ===
# Model: "FLUX" (model_id=618692) by Black Forest Labs
# Pro 1.1 has best on-site gen ratio (~30%) since it's API-only
CIVITAI_MODEL_VERSIONS = [
    (618692, 922358),    # Pro 1.1 — ~902K gens, ~30% on-site (API-only)
    (618692, 1088507),   # Pro 1.1 Ultra — ~1.6M gens, ~4% on-site (API-only)
    (618692, 691639),    # Dev — ~14.4M gens, ~1-4% on-site (open-weight)
    (618692, 699279),    # Schnell — ~2.9M gens, ~0-4% on-site (open-weight)
    (618692, 2068000),   # Krea Dev — ~113K gens, newest
    (1672021, 1892509),  # Kontext [Pro] — 100+ gallery items, ~12% on-site
    (1672021, 1892523),  # Kontext [Max] — small (12 items)
]
CIVITAI_TOOL_ID = None  # Do not use tool_id

# === Scraping: Higgsfield ===
# Only flux_kontext available (94 posts). No FLUX.1 base models.
# Kontext mixes real content — annotate as flux_kontext in metadata.
HIGGSFIELD_API_BASE = "https://fnf.higgsfield.ai/publications/community"
HIGGSFIELD_MODELS = ["flux_kontext"]
HIGGSFIELD_COOKIES_PATH = "data/cookies-higgsfield.txt"
HIGGSFIELD_PAGE_SIZE = 50

# === Scraping: Yodayo ===
# FLUX.1 Dev (~4,400 posts) and Schnell (~750 posts) available.
# CRITICAL: 64.5% of Dev and 30.5% of Schnell images have LoRAs applied.
# YODAYO_REJECT_LORA filters posts with non-empty extra_networks.
YODAYO_MODELS = {
    "flux_dev": "d5d0dae7-93e5-47a0-9d45-79687078db65",
    "flux_schnell": "be2fa7fb-aa53-4b9d-8f2f-72e41bf63762",
}
YODAYO_REJECT_LORA = True  # Filter out LoRA-contaminated images

# === Scraping: Reddit ===
# Avoided per user request — Civitai volume is more than sufficient.
REDDIT_SUBREDDITS = []
REDDIT_SEARCH_QUERIES = []

# === Scraping: Twitter/X ===
# No official FLUX bot account on X.com
TWITTER_BOT_USERNAME = None

# === Safety / provenance ===
# FLUX open-weight has NO safety filters — expect NSFW content
# Only reject exposed genitals (same policy as Seedream)
BLOCKED_CONTENT_TAGS = [
    "penis", "vagina", "vulva", "genitals", "testicle",
    "labia", "clitoris", "phallus",
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
CIVITAI_DOWNLOAD_WORKERS = 4  # Concurrent CDN download workers
HIGGSFIELD_DELAY = (3.0, 7.0)

# === Scraping: Tensor.Art ===
# FLUX tag page: https://tensor.art/tag/757298563872127859 (~1.1M posts)
# All images have full generation metadata (base model, LoRAs, prompt, dimensions).
# Cloudflare-protected — scraper uses Playwright bootstrap then plain requests.
TENSORART_API_DELAY = (2.0, 5.0)       # Delay between API pages
TENSORART_DOWNLOAD_DELAY = (0.5, 1.5)  # Delay between image downloads
TENSORART_DOWNLOAD_WORKERS = 4

# === Scraping: Freepik ===
# Freepik Stock Content API — AI-generated images only.
# Cannot filter by specific model (FLUX vs Imagen vs Mystic).
# Download all AI-generated photos, then filter by resolution/aspect heuristics.
# API key required: https://www.freepik.com/developers/dashboard
# Pagination caps at page 100, up to 100 items/page = max 10,000 items.
FREEPIK_API_DELAY = (2.0, 5.0)      # Delay between search pages
FREEPIK_DOWNLOAD_DELAY = (0.5, 2.0)  # Delay between image downloads
FREEPIK_DOWNLOAD_WORKERS = 4
