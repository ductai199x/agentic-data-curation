"""Instagram Real Photographers — config for scraping real (non-AI) images."""

NAME = "instagram_real"
DISPLAY_NAME = "Instagram Real Photographers"

INSTAGRAM_COOKIES_PATH = "data/cookies/cookies-instagram.txt"

# Accounts organized by AI-editing likelihood tier
# Less likely = strongest "real" signal (photojournalists, news orgs)
# More likely = fashion/editorial (heavy retouching but still camera-captured)
# Highly likely = creative/conceptual (heavy compositing, may blur the line)

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

# Flatten for backward compat (all accounts)
INSTAGRAM_USERNAMES = []
for tier_accounts in INSTAGRAM_TIERS.values():
    INSTAGRAM_USERNAMES.extend(tier_accounts)

# Minimal validation — filter text overlays only, no resolution filtering
EXPECTED_FORMATS = ["JPEG", "PNG", "WEBP"]
MIN_PIXELS = 0              # accept all sizes
MAX_AVG_QUANTIZATION = None # disable compression check — Instagram recompresses everything
MAX_PIXELS = 999_999_999
KNOWN_ASPECT_RATIOS = []    # accept all aspect ratios
ASPECT_RATIO_TOLERANCE = 1.0

# Content filtering — only reject images with text/overlays
REJECT_KEYWORDS = [
    "text", "watermark", "screenshot", "meme", "infographic",
    "comic", "cartoon", "illustration", "logo", "banner",
    "advertisement", "collage", "poster", "flyer", "caption",
    "subtitle", "title_card", "graphic_design",
    "grayscale", "black and white", "monochrome",
]
TEXT_PAIRED_KEYWORDS = []
TEXT_INDICATORS = []
BLOCKED_CONTENT_TAGS = []
CAMERA_EXIF_TAGS = []  # don't reject camera EXIF — these ARE real photos
REJECT_BORDERS = True  # reject scanned photos with white/black borders
