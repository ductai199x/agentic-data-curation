"""FLUX.2 — generator configuration.

Black Forest Labs' second-generation Multimodal Diffusion Transformer (MMDiT).
- FLUX.2 [pro/flex/dev]: Released November 25, 2025
- FLUX.2 [max]: Released December 16, 2025
- FLUX.2 [klein] 4B/9B: Released January 15, 2026

Architecture: 32B param rectified flow transformer with Mistral text encoder.
Pro/Max/Flex are API-only; Dev/Klein are open-weight.
"""

# === Generator identity ===
NAME = "flux2"
DISPLAY_NAME = "FLUX.2 (Black Forest Labs)"

# === Image characteristics ===
EXPECTED_FORMATS = ["JPEG", "PNG", "WEBP"]
MIN_PIXELS = 200_000      # FLUX.2 can go down to 64x64 but quality degrades
MAX_PIXELS = 5_000_000    # Up to 4MP (2048x2048). Give margin.

# JPEG quantization: Civitai CDN serves as JPEG
MAX_AVG_QUANTIZATION = 40.0

# Known aspect ratios — FLUX.2 accepts any ratio (multiples of 16)
# Same presets as FLUX.1 since same dimension constraints
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
    (5, 4),       # 5:4
    (4, 5),       # 4:5
    (7, 4),       # 7:4
    (4, 7),       # 4:7
    (2, 1),       # 2:1
    (1, 2),       # 1:2
]
ASPECT_RATIO_TOLERANCE = 0.06  # 6% tolerance

# EXIF: presence of camera tags = NOT FLUX output
CAMERA_EXIF_TAGS = [
    "Make", "Model", "ExposureTime", "FNumber",
    "ISOSpeedRatings", "FocalLength",
]

# === Scraping: Civitai ===
# Model: "Flux.2" (model_id=2165902) by theally (official BFL)
CIVITAI_MODEL_VERSIONS = [
    (2165902, 2439067),   # Dev — deep gallery, ~10% on-site
    (2165902, 2439442),   # Pro — deep gallery
    (2165902, 2547175),   # Max — deep gallery, ~4% on-site
    (2165902, 2439047),   # Flex — deep gallery
]
CIVITAI_TOOL_ID = None

# === Scraping: Higgsfield ===
# flux_2 has 302 posts, all "pro" variant
HIGGSFIELD_API_BASE = "https://fnf.higgsfield.ai/publications/community"
HIGGSFIELD_MODELS = ["flux_2"]
HIGGSFIELD_COOKIES_PATH = "data/cookies-higgsfield.txt"
HIGGSFIELD_PAGE_SIZE = 50

# === Scraping: Reddit ===
REDDIT_SUBREDDITS = []
REDDIT_SEARCH_QUERIES = []

# === Scraping: Twitter/X ===
TWITTER_BOT_USERNAME = None

# === Safety / provenance ===
# FLUX.2 has built-in safety filters (safety_tolerance 0-5)
# Open-weight (dev/klein) can bypass. API variants enforce.
# Only reject exposed genitals (same policy as FLUX.1)
BLOCKED_CONTENT_TAGS = [
    "penis", "vagina", "vulva", "genitals", "testicle",
    "labia", "clitoris", "phallus",
]

# === Content classification (JoyCaption / VLM) ===
REJECT_KEYWORDS = [
    # Explicit genital exposure only
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

# === Scraping: Tensor.Art ===
# Override base model filter to accept FLUX.2 variants instead of FLUX.1
TENSORART_ACCEPTED_BASE_MODELS = {
    "FLUX.2",
    "Flux.2 Klein 9B",
    "Flux.2 Klein 9B-base",
    "Flux.2 Klein 4B-base",
}

# === Rate limiting ===
REQUEST_DELAY = (1.0, 5.0)
CIVITAI_API_DELAY = (3.0, 6.0)
CIVITAI_DOWNLOAD_DELAY = (0.5, 1.5)
CIVITAI_DOWNLOAD_WORKERS = 4
HIGGSFIELD_DELAY = (3.0, 7.0)
