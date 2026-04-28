"""Instagram Real Photographers — config for scraping real video content.

Uses the same account list as instagram_real.py but scrapes video posts/reels.
Videos are validated with JoyCaption (text overlay detection) and scene cut detection,
then cut into 30s clips for vFSD training.
"""

# === Generator identity ===
NAME = "instagram_real_video"
DISPLAY_NAME = "Instagram Real Videos"
MEDIA_TYPE = "video"  # "image" or "video"

# === Source config ===
COOKIES_PATH = "data/cookies/cookies-instagram.txt"
OUTPUT_DIR = "data/videos/real/instagram"

# Reuse the same account tiers from the image config
INSTAGRAM_TIERS = {
    "less_likely": [
        "natgeo", "nytimes", "time", "motaz_azaiza", "humansofny",
        "reuters", "apnews", "bbcnews", "washingtonpost", "theatlantic",
        "magnumphotos", "worldpressphoto", "gettyimages", "afpphoto",
        "everydayafrica", "everydayasia", "everydaymiddleeast",
        "burnmagazine",
        "joelsartore", "franslanting",
        "thomaspeschak", "paulnicklen",
        "amivitale", "irablockphoto",
        "pedromcbride",
        "michaelchristopherbrown",
        "tomhegen.de",
        "fujilove", "canonuk", "nikoneurope",
        "leica_camera",
        "lightroom", "500px", "flickr",
        "streetphotographyinternational",
        "streetleaks",
        "streetsgrammer",
        "photocinematica",
        "fromstreetswithlove", "urbanstreetphotogallery",
        "observecollective",
        "streetphotographers",
        "street_avengers", "capturestreets",
        "lenspersia",
        "colbybrownphotography",
        "marcadamus",
        "petesouza", "whitehouse",
        "pulitzercenter",
        "1stdibs", "cnn", "thenewyorker",
        "rollingstone", "harpersbazaarus", "townandcountrymag",
        "wsjmag", "billboard", "cosmopolitan",
        "outdoorphotomag",
        "naturephotoportal",
        "audubonsociety", "bbcearth",
        "discoverwildlife",
        "oceanconservancy", "oceana", "surfrider",
        "thephotosociety", "natgeotravel",
        "beautifuldestinations", "earthpix",
        "discoverearth", "fantastic_earth",
        "wonderful_places",
        "tasteintravel", "cntraveler",
        "lonelyplanet", "passionpassport",
        "theplanetd", "travelandleisure", "globewanderer",
        "forbestravelguide", "voyaged", "travelawesome",
    ],
    "more_likely": [
        "voguemagazine", "britishvogue", "gq", "mariotestino",
        "vanityfair", "bazaaruk", "lofficielusa",
        "interviewmag",
        "elleusa", "marieclairemag",
        "evachen212",
        "fashnberry",
        "ninagarcia",
        "artbasel",
        "gagosian", "sothebys", "christiesinc",
        "helmutlang", "ellenvonunwerth",
        "davidsims_", "inezandvinoodh", "patrickdemarchelier",
        "timwalker_",
        "nadavkander", "gregwilliams",
        "elizavetaporodina",
        "tannybrown",
        "jessicakobeissi",
        "duffysworld", "niconielsen",
        "edingtonphoto",
        "rankinarchive", "simonlekias",
        "tomhicks",
        "joeymancuso",
        "tylersphotos",
        "scottborrero", "theglassmagazine",
        "papermagazine", "ilovedust",
        "10magazine", "narcissemagazine", "lofficielitalia",
        "fashionphotographyappreciation",
        "fashioncanada", "graziauk",
        "tataborello", "imaxtree",
        "cfda",
        "fubiz",
        "ignant", "itsnicethat", "thisiscolossal",
        "designboom", "dezeen", "framemagazine",
        "wallpapermag", "tmagazine", "thecut", "manoftheworld",
        "esquire", "complexstyle", "highsnobiety",
        "hypebeast",
    ],
    "highly_likely": [
        "stevemccurryofficial", "muradosmann", "jordi.koalitic",
        "brandonwoelfel", "danielkordan", "maxrivephotography",
        "brahmino", "hobopeeba",
        "nois7",
        "zachallia", "omarzrobles",
        "mattcrump", "mikekus",
        "alexstrohl", "samuelelkins",
        "bennyharlem",
        "taylormichaelburk",
    ],
}

# Flatten all accounts
INSTAGRAM_USERNAMES = []
for _tier_accounts in INSTAGRAM_TIERS.values():
    INSTAGRAM_USERNAMES.extend(_tier_accounts)

# === Scraping parameters ===
MAX_VIDEOS = 99999
MAX_PER_USER = 99999
VIDEOS_PER_VISIT = 20       # Round-robin: download N per account per visit
STALE_VISITS_TO_EXHAUST = 3  # Mark account exhausted after N zero-download visits

# === Video validation ===
MIN_DURATION = 10            # Discard videos shorter than this (seconds)
CLIP_DURATION = 15           # Cut validated clips to this length (seconds)
MIN_CLEAN_SEGMENT = 15       # Minimum scene-cut-free segment to extract a clip
MAX_CLIPS_PER_VIDEO = 4      # Max clips to extract from a single video
SCENE_CUT_THRESHOLD = 0.25   # Frame diff threshold for scene cut detection

# === Content filtering (JoyCaption) ===
# For Instagram video: text overlays are OK (flagged, not rejected)
# We still reject non-camera content (animation, CGI, etc.)
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

# Text overlay keywords — NOT rejected, but flagged in metadata
TEXT_OVERLAY_KEYWORDS = [
    "text overlay", "text", "caption", "subtitle",
    "lower third", "news ticker", "title card",
    "watermark", "logo", "banner",
    "overlay",
]

# Keyword combos — reject if ALL keywords in a combo are present
REJECT_COMBOS = []

# === Media characteristics ===
EXPECTED_FORMATS = ["MP4", "WEBM"]
MAX_HEIGHT = 1080
