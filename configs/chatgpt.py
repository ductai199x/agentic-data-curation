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
# EXTREMELY strict filtering. Key constraint:
# - Before March 25, 2025: ChatGPT used DALL-E 3 (different model)
# - After April 1, 2025: All ChatGPT tiers use GPT-Image-1 (native 4o)
# - After Dec 16, 2025: GPT-Image-1.5 became default
# Date gate: only posts after April 1, 2025 (Unix 1743465600)
# Flair gate: only posts with explicit ChatGPT/GPT-4o image flairs
REDDIT_SUBREDDITS = [
    "aiArt",        # Best: "Image - ChatGPT" flair, ~25 posts/day, 67% PNG
    "dalle2",       # "GPT-4o" flair, ~130 total posts, explicit model tag
]
REDDIT_SEARCH_QUERIES = [
    '"gpt-image-1" subreddit:aiArt',
    '"gpt-image-1" subreddit:dalle2',
    '"gpt-image-1" subreddit:OpenAI',
    '"chatgpt image generation" subreddit:aiArt',
    '"gpt-4o image" subreddit:aiArt',
    '"gpt-4o image" subreddit:dalle2',
]

# Date gate: April 1, 2025 00:00 UTC (all ChatGPT tiers have GPT-Image-1)
REDDIT_MIN_CREATED_UTC = 1743465600

# Flair gate: ONLY download posts with these exact flairs
# This is the strictest filter — posts without these flairs are skipped entirely
REDDIT_REQUIRE_FLAIRS = {
    # r/AIArt — generator-specific flair
    "image - chatgpt :a2:", "image - chatgpt",
    # r/dalle2 — model-specific flair
    "gpt-4o",
}

# --- Reddit post filtering ---
REDDIT_REJECT_FLAIRS = {
    "Discussion", "Question", "Help", "News", "News Article",
    "ANNOUNCEMENT", "Mod Post", "Research", "Tutorial", "Guide",
    "Video", "Music", "Text", "Politics", "Sora",
    "GPTs", "Project", "Miscellaneous", "Unverified",
    "Prompt", "Programming", "Writing", "Commercial",
    # Other generators — must not contaminate
    "Stable Diffusion", "Nightcafe", "FLUX", "Midjourney",
    "Image - Google Gemini", "Image - Stable Diffusion",
    "Image - Midjourney", "Image - FLUX", "Image - SoraAI",
    "Image - Nightcafe", "Image - Bing Image Creator",
    "Image - Microsoft Copilot",
    # DALL-E flairs — different model, not GPT-Image
    "DALL·E 3", "DALL-E 3", "dalle-3", "DALL·E 2",
}

REDDIT_REJECT_TITLE_KEYWORDS = [
    # Multi-generator comparisons
    " vs ", " vs.", "versus", "comparison", "compared to",
    "benchmark", "ranking", "showdown", "side by side", "side-by-side",
    # Other generators mentioned
    "midjourney", "stable diffusion", "flux", "gemini",
    "grok", "ideogram", "seedream", "nano banana",
    "dall-e", "dalle",
    # Screenshots / complaints
    "screenshot", "bug", "error", "issue", "help",
    "why does", "why is", "how to", "glitch",
    "censored", "jailbreak", "banned", "guardrails",
    "rate limit", "too many requests",
    # Meme formats
    "pov:", "when you", "me when", "mfw", "tfw",
    "meme", "change my mind",
    # Meta
    "petition", "boycott", "update", "changelog",
    "subscription", "pricing", "limit", "cap", "api",
    "review",
]

REDDIT_ALLOWED_IMAGE_DOMAINS = {
    "i.redd.it",
    "preview.redd.it",
    "i.imgur.com",
}

REDDIT_SKIP_SELF_POSTS = True

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
    # Technical / error
    "error message", "error screen", "loading screen",
    "code snippet", "terminal", "command line",
    "source code", "stack trace",
    "api response", "json output", "xml output",
    # Unambiguous data/document content
    "spreadsheet", "powerpoint", "presentation slide",
    # Leaderboards / rankings
    "leaderboard", "ranking", "scoreboard",
    # Graphic design / clipart (unambiguous non-photo terms only)
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
