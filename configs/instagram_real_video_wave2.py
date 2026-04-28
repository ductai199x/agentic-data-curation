"""Instagram Real Video Wave 2 — video-heavy accounts (news, sports, drone, timelapse).

Extends the original instagram_real_video.py with accounts selected for high
video output. Same output directory so clips merge with wave 1.
"""

# === Generator identity ===
NAME = "instagram_real_video_wave2"
DISPLAY_NAME = "Instagram Real Videos (Wave 2)"
MEDIA_TYPE = "video"

# === Source config ===
COOKIES_PATH = "data/cookies/cookies-instagram.txt"
OUTPUT_DIR = "data/videos/real/instagram"  # Same dir as wave 1

INSTAGRAM_TIERS = {
    "timelapse": [
        "matjoez",            # City/travel timelapse filmmaker
        "emerictimelapse",    # Hyperlapse specialist
        "filmspektakel",      # Timelapse production company
        "mikeolbinski",       # Emmy-winning storm chaser
        "dustin_farrell",     # Storm/motion-control timelapse
        "stormvisuals",       # Hurricane/severe weather video
        "dakotalapse",        # Night sky/Milky Way timelapse
        "alynjw",             # Astro/landscape timelapse
        "andrewmccarthy",     # Moon/space photography+video
        "earthcam",           # Construction timelapse + city webcams
    ],
    "drone": [
        "johnny_fpv",         # Premier FPV cinematographer
        "nurkfpv",            # Drone racing world champion, Emmy winner
        "rotor_riot",         # FPV community, multiple pro pilots
        "fromwhereidrone",    # Landscape drone
        "airpixels",          # Abstract aerial landscapes
        "saltywings",         # Australian aerial video
        "thedronecreative",   # Drone cinematography
        "prohdigyy",          # FPV + travel filmmaking
    ],
    "news": [
        "nbcnews",
        "abcnews",
        "cbsnews",
        "skynews",
        "guardian",
        "ajplus",
        "foxnews",
        "pbs",
        "cbcnews",
        "euronews",
    ],
    "sports": [
        "nba",
        "nfl",
        "espn",
        "sportscenter",
        "f1",
        "olympics",
        "premierleague",
        "gopro",
        "redbull",
    ],
    "film_music": [
        "a24",
        "coachella",
        "tomorrowland",
        "sundanceorg",
        "sxsw",
    ],
}

INSTAGRAM_USERNAMES = []
for _tier_accounts in INSTAGRAM_TIERS.values():
    INSTAGRAM_USERNAMES.extend(_tier_accounts)

# === Scraping parameters ===
MAX_VIDEOS = 99999
MAX_PER_USER = 99999
VIDEOS_PER_VISIT = 20
STALE_VISITS_TO_EXHAUST = 3

# === Video validation (same as wave 1) ===
MIN_DURATION = 10
CLIP_DURATION = 15
MIN_CLEAN_SEGMENT = 15
MAX_CLIPS_PER_VIDEO = 4
SCENE_CUT_THRESHOLD = 0.25

# === Content filtering (same as wave 1) ===
REJECT_KEYWORDS = [
    "cartoon", "animated", "animation", "anime",
    "illustration", "3d render", "3d rendering",
    "cgi", "video game",
    "slideshow", "montage", "compilation",
    "intro", "outro", "subscribe", "like and share",
    "green screen", "chroma key", "virtual background",
    "picture-in-picture", "split screen",
    "infographic",
    "graphic design",
    "digital interface",
    "screenshot", "screen recording", "screen capture",
    "phone screen", "smartphone screen",
    "app interface", "user interface",
    "advertisement", "product advertisement",
]

TEXT_OVERLAY_KEYWORDS = [
    "text overlay", "text", "caption", "subtitle",
    "lower third", "news ticker", "title card",
    "watermark", "logo", "banner",
    "overlay",
]

REJECT_COMBOS = []

# === Media characteristics ===
EXPECTED_FORMATS = ["MP4", "WEBM"]
MAX_HEIGHT = 1080
