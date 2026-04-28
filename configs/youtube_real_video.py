"""YouTube Real Videos — config for downloading real camera-captured video.

Downloads 4-minute chunks from verified YouTube channels across 21 content
categories. Chunks are processed into validated 60s clips for vFSD training.

Channels are pre-screened via deep screening (JoyCaption + scene detection)
and stored in configs/video_sources/verified/*.txt.
"""

# === Generator identity ===
NAME = "youtube_real_video"
DISPLAY_NAME = "YouTube Real Videos"
MEDIA_TYPE = "video"

# === Source config ===
COOKIES_PATH = "data/cookies/cookies-youtube.txt"
# OUTPUT_DIR is the dataset ROOT — downloaders join "staging/<cat>/", the
# validation pipeline writes to "validated/<cat>/" and "rejected/<cat>/".
OUTPUT_DIR = "data/videos/real/youtube"
VERIFIED_CHANNELS_DIR = "configs/video_sources/verified"

# === Download parameters ===
MAX_HEIGHT = 1080
CHUNK_DURATION = 240          # 4-minute chunks
SKIP_START = 120              # Skip first 2 minutes (intro)
SKIP_END = 120                # Skip last 2 minutes (outro)
MIN_VIDEO_DURATION = 60       # Skip videos shorter than this
VIDEOS_PER_CHANNEL = 20       # How many videos to list per channel
DOWNLOAD_WORKERS = 1          # Concurrent download threads

# === Video validation / processing ===
MIN_DURATION = 10             # Discard clips shorter than this
CLIP_DURATION = 30            # Cut validated clips to this length (seconds)
MIN_CLEAN_SEGMENT = 30        # Minimum scene-cut-free segment to extract a clip
MAX_CLIPS_PER_VIDEO = 8       # Max clips per source — 8 × 30s matches prior 4 × 60s coverage while doubling sample count
SCENE_CUT_THRESHOLD = 0.25    # Frame diff threshold for scene cut detection

# === Content filtering (JoyCaption) ===
REJECT_KEYWORDS = [
    "news anchor", "news studio",
    "digital interface",
    "graphic design",
    "cgi", "3d render", "3d rendering",
    "video game",
    "cartoon", "animated", "animation", "anime",
    "illustration",
    "slideshow", "montage", "compilation",
    "intro", "outro", "subscribe", "like and share",
    "lower third", "news ticker",
    "green screen", "chroma key", "virtual background",
    "picture-in-picture", "split screen",
    "infographic",
    "text overlay",
]

# Text overlay keywords — flagged in metadata (for YouTube, these also reject)
TEXT_OVERLAY_KEYWORDS = [
    "text overlay", "text", "caption", "subtitle",
    "lower third", "news ticker", "title card",
    "watermark", "logo", "banner",
    "overlay",
]

# Keyword combos — reject if ALL keywords in a combo are present
REJECT_COMBOS = [
    ("overlay", "text"),
    ("graphics", "overlay"),
]

# === Media characteristics ===
EXPECTED_FORMATS = ["WEBM", "MKV", "MP4"]

# === Content categories (must match files in VERIFIED_CHANNELS_DIR) ===
CATEGORIES = [
    "C01_people_casual",
    "C02_people_action",
    "C03_talking_head",
    "C04_lecture",
    "C05_nature_landscape",
    "C06_nature_wildlife",
    "C07_nature_water",
    "C08_walking_biking_tour",
    "C09_urban_street",
    "C10_urban_architecture",
    "C11_vehicles_exterior",
    "C12_vehicles_pov",
    "C13_cooking",
    "C14_product_review",
    "C15_animals_domestic",
    "C16_hands_objects",
    "C17_aerial_drone",
    "C18_weather_atmosphere",
    "C19_macro_texture",
    "C20_security_camera",
    "C21_indoor_everyday",
]
