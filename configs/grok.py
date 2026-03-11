"""Grok (Aurora model) — generator configuration.

Known metadata gathered from analysis on 2026-03-11.
Source: 123 images from Grok Imagine public gallery.
"""

# Native output resolutions (width, height)
# Images not matching these are likely thumbnails, uploads, or screenshots
NATIVE_RESOLUTIONS = [
    (784, 1168),   # portrait (most common — 76/109 detected images)
    (1168, 784),   # landscape
    (832, 1248),   # portrait alt
    (1248, 832),   # landscape alt
]

# Resolution tolerance (pixels) for matching
RESOLUTION_TOLERANCE = 2

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

# Maximum dimension — images larger than this are likely real uploads
MAX_LONG_SIDE = 1400

# Minimum dimension — images smaller than this are likely thumbnails
MIN_LONG_SIDE = 700

# Scraping config
GALLERY_URL = None  # TBD — need to identify the exact gallery URL
REQUEST_DELAY_RANGE = (1.0, 5.0)  # random uniform delay between requests (seconds)
MAX_RETRIES = 3
BACKOFF_BASE = 2.0  # exponential backoff base (seconds)
