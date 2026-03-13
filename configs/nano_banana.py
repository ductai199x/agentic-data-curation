"""Nano Banana — generator configuration.

Google's Nano Banana AI image generator (consumer name for Gemini Image).
Three versions:
  - Nano Banana (v1): Gemini 2.5 Flash Image (Aug 2025)
  - Nano Banana Pro: Gemini 3 Pro Image Preview (Nov 2025)
  - Nano Banana 2: Gemini 3.1 Flash Image Preview (Feb 2026)

All outputs include SynthID (invisible watermark) and C2PA metadata.
"""

# === Generator identity ===
NAME = "nano_banana"
DISPLAY_NAME = "Nano Banana"

# === Image characteristics ===
EXPECTED_FORMATS = ["JPEG", "PNG", "WEBP"]
MIN_PIXELS = 650_000     # Filters 512x512 (262k) and small thumbnails. 1K tier smallest is ~1Mpx.
MAX_PIXELS = 18_000_000  # 4K tier largest is ~17.2M (4800x3584)

# JPEG quantization: Nano Banana outputs high quality
MAX_AVG_QUANTIZATION = 40.0

# Known aspect ratios from Google API docs
# All versions: 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9
# Nano Banana 2 adds: 1:4, 4:1, 1:8, 8:1
KNOWN_ASPECT_RATIOS = [
    (1, 1),       # 1:1
    (2, 3),       # 2:3
    (3, 2),       # 3:2
    (3, 4),       # 3:4
    (4, 3),       # 4:3
    (4, 5),       # 4:5
    (5, 4),       # 5:4
    (9, 16),      # 9:16
    (16, 9),      # 16:9
    (21, 9),      # 21:9
    # Nano Banana 2 additions
    (1, 4),       # 1:4
    (4, 1),       # 4:1
    (1, 8),       # 1:8
    (8, 1),       # 8:1
]
ASPECT_RATIO_TOLERANCE = 0.05  # 5% tolerance for rounding

# EXIF: presence of camera tags = NOT Nano Banana output
CAMERA_EXIF_TAGS = [
    "Make", "Model", "ExposureTime", "FNumber",
    "ISOSpeedRatings", "FocalLength",
]

# === Scraping: Civitai ===
# On-site generation model versions (0 generations available — NOT viable)
# Each entry: (model_id, model_version_id)
CIVITAI_MODEL_VERSIONS = [
    (1903424, 2154472),   # Nano Banana v1
    (1903424, 2436219),   # Nano Banana Pro
    (1903424, 2725610),   # Nano Banana 2
]
CIVITAI_TOOL_ID = None  # No tool_id found

# === Scraping: Higgsfield ===
# Community gallery API: GET fnf.higgsfield.ai/publications/community
# /community returns ALL posts (approved + user-published). /community/approved is curated only (69 total).
# Cursor-based pagination, full-res PNGs on CloudFront CDN
# model=nano_banana (~1,487 images), model=nano_banana_2 (~10,888 images)
HIGGSFIELD_API_BASE = "https://fnf.higgsfield.ai/publications/community"
HIGGSFIELD_MODELS = ["nano_banana", "nano_banana_2"]
HIGGSFIELD_COOKIES_PATH = "data/cookies-higgsfield.txt"
HIGGSFIELD_PAGE_SIZE = 50  # Server max is ~50

# === Scraping: Reddit ===
# r/Gemini is a CRYPTO sub — skip it
REDDIT_SUBREDDITS = [
    "GoogleGemini",
    "nanobanana",
    "AiGeminiPhotoPrompts",  # Best source: 94% image density, 52 posts/day
]
REDDIT_SEARCH_QUERIES = [
    '"nano banana"',
    '"made with nano banana"',
    '"nano banana pro"',
    '"nano banana 2"',
    '"gemini image generation"',
    '"gemini generated"',
    'flair:"Image Generation" subreddit:Gemini',
    'flair:"Nano Banana" subreddit:Gemini',
]
REDDIT_AI_ART_FLAIRS = {
    "AI ART", "AI Art", "ai art", "Image Generation", "Image",
    "Nano Banana", "Creation", "Showcase", "Gallery", "Generated Image",
    # r/AiGeminiPhotoPrompts — ONLY these two flairs
    "Photorealistic Style", "📸 Photorealistic Style",
    "🎨 ShowCase", "ShowCase",
}

# --- Reddit post filtering ---
REDDIT_REJECT_FLAIRS = {
    # Discussion / meta
    "Discussion", "Question", "Help", "Help!", "Meta", "Feedback",
    "Announcement", "Poll", "Rant", "Debate",
    "Bug", "Feature Request", "Issue",
    # Meme / humor
    "Meme", "Humor", "Funny", "Shitpost",
    # Non-image content
    "News", "News/Product Leak", "Article", "Comparison", "Video",
    # r/nanobanana specific — keep Showcase, Prompt, Prompt + Tutorial
    # r/AiGeminiPhotoPrompts — only keep 🎨 ShowCase and 📸 Photorealistic Style
    "Abstract & Concept Art", "Prompt Engineering / Tips", "Community", "Request a Prompt",
    # r/GoogleGemini specific
    "Miscellaneous", "Memes",
    # Gemini-specific non-image flairs
    "Gemini Advanced", "Gemini Nano", "Bard", "API",
    "Code", "Android", "iOS", "Mod Post",
}

REDDIT_REJECT_TITLE_KEYWORDS = [
    # Comparisons / benchmarks
    " vs ", " vs.", "versus", "comparison", "compared to", "better than",
    "benchmark", "ranking", "tier list", "side by side", "side-by-side",
    "before/after", "before and after",
    # Help / troubleshooting
    "help", "how to", "can't", "error", "bug", "issue", "why ",
    "question", "tutorial", "guide", "tips",
    # Censorship / moderation drama
    "censored", "moderated", "content moderation", "censorship",
    "ban ", "banned", "jailbreak", "jailbroken",
    "bring back", "uncensored",
    # Meme formats
    "pov:", "when you", "me when", "mfw", "mrw", "tfw",
    "unpopular opinion", "hot take", "am i the only",
    "change my mind",
    # Advocacy / meta
    "petition", "protest", "boycott",
    "goodbye", "rip ", " rip,",
    "update", "changelog", "release notes",
    # Other generators (comparison posts)
    "midjourney", "dall-e", "dalle", "stable diffusion",
    "grok", "ideogram", "flux", "seedream",
    "chatgpt image",
    # Pricing / subscription
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
TWITTER_BOT_USERNAME = "NanoBanana"
TWITTER_MEDIA_URL = "https://x.com/NanoBanana/media"
TWITTER_COOKIES_PATH = "data/cookies-x.txt"
TWITTER_SEARCH_QUERIES = [
    "@NanoBanana generate",
    "@NanoBanana create",
    "@NanoBanana make",
    "@NanoBanana draw",
    "@NanoBanana can you generate",
    "@NanoBanana can you make",
    "@NanoBanana image of",
    "@NanoBanana picture of",
]

# === Safety / provenance ===
# Nano Banana hard-blocks: nudity, sexual content, violence/gore, hate, deepfakes, minors
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
CIVITAI_API_DELAY = (5.0, 12.0)
CIVITAI_DOWNLOAD_DELAY = (1.0, 3.0)
TWITTER_SEARCH_DELAY = (3.0, 8.0)
HIGGSFIELD_DELAY = (3.0, 7.0)  # Be conservative — ~12K posts to scrape, don't get banned
