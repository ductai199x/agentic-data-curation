"""Sora — OpenAI video/image generation model configuration.

Sora is OpenAI's video generation model, accessible via sora.chatgpt.com.
The platform is shutting down April 26, 2026. Priority: archive as much as possible.

Sora generates both videos (mp4, 5-20s, 480p-1080p) and images (png, 1024px).

API notes:
  - /backend/public/feed returns ~46 curated items (no auth, no pagination)
  - /backend/feed/videos?limit=24&after=CURSOR — authenticated paginated feed
  - /backend/generations/{id}/download returns download URL (needs bearer token)
  - Feed variants: videos, images, featured, recent, ranked
  - curl_cffi with Chrome TLS impersonation bypasses Cloudflare
  - Bearer token from /api/auth/session (ChatGPT session cookie)
  - Sentinel PoW token from browser (saved in data/images/sora/sentinel_token.json)
  - Video source URLs (encodings.source.path) are signed Azure Blob URLs, no auth needed
"""

# === Generator identity ===
NAME = "sora"
DISPLAY_NAME = "Sora (OpenAI)"

# === Media characteristics ===
EXPECTED_FORMATS = ["MP4", "PNG", "WEBP", "JPEG"]
MIN_PIXELS = 200_000       # Images only; videos skip pixel check
MAX_PIXELS = 20_000_000

# Videos: 480p to 1080p, 5-20 seconds, 150-600 frames
# Images: typically 1024x1024, 1024x1536, 1536x1024
KNOWN_ASPECT_RATIOS = [
    (16, 9),      # 1920x1080, 1080x608
    (9, 16),      # 1080x1920, 608x1080
    (1, 1),       # 1024x1024
    (2, 3),       # 1024x1536, 720x1080
    (3, 2),       # 1536x1024, 1080x720
    (4, 3),       # landscape
    (3, 4),       # portrait
    (9, 16),      # 480x854 (low-res vertical)
]
ASPECT_RATIO_TOLERANCE = 0.08

# === Scraping: Sora ===
SORA_BASE_URL = "https://sora.chatgpt.com"
SORA_COOKIES_PATH = "data/cookies/cookies-sora.txt"

# === Rate limiting ===
# Conservative — this is OpenAI's platform
API_DELAY = (3.0, 5.0)         # Between API pagination calls
DOWNLOAD_DELAY = (2.0, 3.0)    # Between media downloads (source URLs are signed, no auth)

# === Content classification (JoyCaption / VLM) ===
# Videos won't go through JoyCaption, but images might
REJECT_KEYWORDS = [
    "penis", "vagina", "vulva", "genitals", "testicle",
    "labia", "clitoris", "phallus",
    "cum", "ejaculation", "cumshot",
    "penetration", "intercourse", "sex act",
    "illustration", "cartoon", "anime", "cgi", "comic",
    "line drawing", "sketch", "digital painting",
    "3d render", "pixel art", "vector art", "watercolor",
    "oil painting", "oil on canvas", "pencil drawing", "manga",
    "screenshot", "user interface", "app interface",
    "meme", "impact font", "text overlay",
]

TEXT_PAIRED_KEYWORDS = []
TEXT_INDICATORS = []
