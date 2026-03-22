NAME = "instagram_ai_influencer"
DISPLAY_NAME = "Instagram AI Influencers"
INSTAGRAM_USERNAMES = [
    # AI Thirst Trap - Adult (15)
    "jessicaa.foster", "emilypellegrini", "millasofiafin", "fit_aitana",
    "viva_lalina", "anazelu", "yoursophieskye", "miazelu",
    "sika.moon.ai", "eager.alice.may", "bella.vegaz", "eva_isabelle12",
    "kaitoledo__", "oliviaroa__", "lexischmidtai",
    # AI-Generated Influencer (36)
    "janky", "therealdayzee", "wellnessmaddie1", "gioalemann",
    "arbie_seo", "aditi.aimuse", "keinmoytod", "kenza.layli",
    "aliciaidris98", "serahreikka", "aina_avtr", "imvu_sofoke",
    "rijiiuji", "soymar.ia", "pip.yourbae", "aiemilyrae",
    "amara_gram", "yimeng_yu", "mishalove_official", "hellejensen.ai",
    "iga.naderi", "lilaziyagil", "bella.ai.model", "em_reyes00",
    "lia_byte", "zoe.valencia.ai", "limaiaaa", "harrismorgan.ic",
    "nyx.chen.ai", "miacorvini", "the.natalia.novak", "ai.serenay",
    "sophia_falkenstein_ai", "oliviaislivinghigh", "noahsvensgaard",
    # User-provided accounts
    "sunny_chijnn", "millasofiaa", "aishaneo", "shudu.gram",
    "kenzalayli", "owol.xx", "nene.ceci",
]
INSTAGRAM_COOKIES_PATH = "data/cookies-instagram.txt"
EXPECTED_FORMATS = ["JPEG", "PNG", "WEBP"]
MIN_PIXELS = 200_000
MAX_PIXELS = 10_000_000
KNOWN_ASPECT_RATIOS = [(1, 1), (4, 5), (5, 4), (16, 9), (9, 16), (3, 4), (4, 3)]
ASPECT_RATIO_TOLERANCE = 0.10  # Instagram crops aggressively
CAMERA_EXIF_TAGS = ["Make", "Model", "ExposureTime", "FNumber", "ISOSpeedRatings"]
REJECT_KEYWORDS = ["illustration", "cartoon", "anime", "cgi", "comic", "screenshot", "3d_render", "pixel_art", "watercolor"]
TEXT_PAIRED_KEYWORDS = ["table", "chart", "conversation", "notification", "infographic"]
TEXT_INDICATORS = ["text", "font", "typed", "data", "numbers", "screenshot"]
BLOCKED_CONTENT_TAGS = ["penis", "vagina", "vulva", "genitals", "testicle", "labia", "clitoris"]
