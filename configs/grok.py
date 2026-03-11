"""Grok (Aurora model) — generator configuration.

Known metadata gathered from analysis on 2026-03-11.
Source: 123 images from Grok Imagine public gallery.

Resolution reference: https://docs.x.ai/developers/model-capabilities/images/generation#aspect-ratio
Supported aspect ratios: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 2:1, 1:2,
                          19.5:9, 9:19.5, 20:9, 9:20, auto
Resolution tiers: "1k" (~915k pixels) and "2k" (TBD, likely ~4MP)
"""

# Resolution strategy: DON'T match exact resolutions.
# With 13+ aspect ratios, two resolution tiers (1k/2k), and unknown rounding,
# exact matching is too brittle. Instead, use bounds-based filtering:
# - Reject thumbnails (long side < MIN_LONG_SIDE)
# - Reject real uploads (long side > MAX_LONG_SIDE)
# - Reject tiny total pixel count (likely thumbnail or heavily downscaled)
#
# Known observed resolutions (for reference only, NOT used for filtering):
# 1k tier: 784x1168, 1168x784, 832x1248, 1248x832, 960x960,
#          720x1280, 1280x720, 896x1344, 1360x768, 1104x832, etc.
NATIVE_RESOLUTIONS = None  # Not used — bounds-based filtering instead

# Expected image formats
EXPECTED_FORMATS = ["JPEG", "PNG"]

# JPEG quantization: Grok outputs very high quality
# avg_q ≈ 1.0 (essentially lossless) for most outputs
# avg_q ≈ 5.77 for some
MAX_AVG_QUANTIZATION = 15.0  # reject if higher (likely re-compressed)

# EXIF patterns
# Some Grok images have: Artist=UUID, ImageDescription="Signature: <base64>"
# This is Grok's C2PA-style provenance watermark
# Presence of camera EXIF (Make, Model, ExposureTime, etc.) = NOT Grok output
CAMERA_EXIF_TAGS = [
    "Make", "Model", "ExposureTime", "FNumber",
    "ISOSpeedRatings", "FocalLength",
]

# Pixel count bounds
# 1k tier: ~915k pixels (784*1168=915712), allow some margin
# 2k tier: ~4M pixels (TBD)
# Thumbnails like 464x688 = 319k pixels — clearly below 1k
MIN_PIXELS = 800_000   # below this = thumbnail or heavily downscaled
MAX_PIXELS = 5_000_000  # above this = likely real upload (e.g., 3072x4608 = 14M)

# Scraping config
GALLERY_URL = None  # TBD — need to identify the exact gallery URL
REQUEST_DELAY_RANGE = (1.0, 5.0)  # random uniform delay between requests (seconds)
MAX_RETRIES = 3
BACKOFF_BASE = 2.0  # exponential backoff base (seconds)
