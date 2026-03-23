"""Instagram Real Photographers — config for scraping real (non-AI) images."""

NAME = "instagram_real"
DISPLAY_NAME = "Instagram Real Photographers"

INSTAGRAM_COOKIES_PATH = "data/cookies-instagram.txt"

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
        "laboratorio_visual", "burnmagazine", "themuslimphoto",
        "documentingiran", "witness.media", "photojournalism_now",
        "bfrphoto", "jimmynelsonofficial", "joelsartore", "franslanting",
        "thomaspeschak", "cristinamittermeier", "paulnicklen",
        "amivitale", "irablockphoto", "andywettsteinphoto",
        "lucashaleybrown", "shanegrayimages", "martinlangephotography",
        "pedromcbride", "chfrenchphotography", "timflach",
        "michaelchristopherbrown", "leonardograntphoto", "carolyndrake",
        "neloliveira.photography", "yorikcostain", "calebjamesfisher",
        "tomhegen.de", "giorgiobaravierfotografo", "carlafrijdphoto",
        "laurentburstvision", "adrianlaudaphoto", "sandro_malandrin",
        "kennosborn", "josefsiebers_photography", "sebastiao.salgado",
        "marcribasphotography", "yannis.davy.guibinga", "hasselbladheroes",
        "aikidomag", "fujilove", "sonya7riii", "canonuk", "nikoneurope",
        "leica_camera", "shotoniphone", "googlepixel_us",
        "lightroom", "adobephotoshop", "500px", "flickr",
        "streetphotographyinternational", "streetphotography.international",
        "repframesmagazine", "streetleaks", "life_is_street",
        "lensculturestreets", "streetsgrammer", "in_public_sp",
        "shadesofsouthasia", "photocinematica", "cobfringe",
        "thisisstreet", "fromstreetswithlove", "urbanstreetphotogallery",
        "streetphotographyhub", "observecollective", "myspc",
        "thestreetphotographyhub", "streetphotographers",
        "street_avengers", "capturestreets", "thelensbetween",
        "lenspersia", "grafreet", "sevfrancis", "mikaelstenberg",
        "curaga_photography", "lisasimonsenphoto",
        "marthafrielphoto", "colbybrownphotography",
        "chris.burkard", "marcadamus", "jeffreylockhart_photo",
        "quentindavidphoto", "stfrancisofthesea",
        "mattymaths", "petesouza", "whitehouse",
        "pulitzercenter", "niloufar.photographs", "tarfrashidi",
        "1stdibs", "cnn", "thenewyorker",
        "rollingstone", "harpersbazaarus", "townandcountrymag",
        "wsjmag", "billboard", "cosmopolitan",
        "outdoorphotomag", "digitalcameraworld",
        "outdoor_photography", "naturephotoportal",
        "audubonsociety", "bbcearth",
        "discoverwildlife", "wildlifeplanet",
        "oceanconservancy", "oceana", "surfrider",
        "thephotosociety", "natgeotravel",
        "beautifuldestinations", "earthpix", "ourplanetdaily",
        "discoverearth", "earthfocus", "fantastic_earth",
        "wonderful_places", "living_destinations",
        "tasteintravel", "cntraveler",
        "lonelyplanet", "passionpassport", "doyoutravel",
        "theplanetd", "travelandleisure", "globewanderer",
        "forbestravelguide", "voyaged", "travelawesome",
    ],
    "more_likely": [
        "voguemagazine", "britishvogue", "gq", "mariotestino",
        "vanityfair", "bazaaruk", "daboramagazine", "lofficielusa",
        "wmagazine", "interviewmag", "crmagazine", "ilovedust",
        "elleusa", "marieclairemag", "allaboreverie",
        "evachen212", "manrepeller", "whoworeit",
        "fashnberry", "gfreedman", "tomdamiani",
        "pfruhan", "caradelevingne_photos", "ninagarcia",
        "andywarholfoundation", "artbasel",
        "gagosian", "sothebys", "christiesinc",
        "photovogueitalia", "annieleibow", "peterlindbergh",
        "helmutlang", "ellenvonunwerth", "mertalasandmarcuspiggott",
        "davidsims_", "inezandvinoodh", "patrickdemarchelier",
        "timwalker_", "luigiandlango", "solvesundsbo",
        "mikael_jansson", "thierrylegoues", "collierschorr",
        "nadavkander", "gregwilliams", "ranaborchertphotography",
        "shangrayphoto", "paologiocoso",
        "reneeroper", "elizavetaporodina", "leilanewmanphoto",
        "tanyarivero", "marianviviani", "gaborjurina",
        "danielriera_studio", "mattieudo", "cameronhammond",
        "saralightphotographer", "harrywedding", "tannybrown",
        "luisahestrada", "laurenkkelp", "cassjustsayyes",
        "carlablanchard.photo", "charleytylerphoto",
        "larajade", "jessicakobeissi", "georginahume",
        "duffysworld", "trfranco", "niconielsen",
        "edingtonphoto", "gilesprice", "rfreedmanphoto",
        "rankinarchive", "gregrainphoto", "simonlekias",
        "zhanghuishan", "jamesmeetfrost", "mrseriph",
        "jackiewaters_", "sarahshotme", "tomhicks",
        "giampaolomiraldiofficial", "joeymancuso",
        "pejmanimage", "martinsweden", "gabrieldesiqueiraphoto",
        "joshreedsphoto", "tylersphotos", "tinysnaps",
        "scottborrero", "thetutuvany", "theglassmagazine",
        "dazedmagazine", "ilovedust", "papermagazine",
        "interviewmag", "metalmagazine", "numéromagazine",
        "10magazine", "narcissemagazine", "lofficielitalia",
        "fashionphotographyappreciation", "editorialphotomag",
        "fashionmodel.nl", "models.com", "tfsmagazine",
        "fashioncanada", "graziauk", "graziadaily",
        "tataborello", "thefashionography", "imaxtree",
        "fashionphotoaward", "photogenicmag", "cfda",
        "maborosi", "fubiz", "thiscollection",
        "ignant", "itsnicethat", "thisiscolossal",
        "designboom", "dezeen", "framemagazine",
        "wallpapermag", "tmagazine", "thecut", "manoftheworld",
        "esquire", "complexstyle", "highsnobiety",
        "hypebeast", "ssaborevi",
    ],
    "highly_likely": [
        "stevemccurryofficial", "muradosmann", "jordi.koalitic",
        "brandonwoelfel", "danielkordan", "maxrivephotography",
        "pfruhan", "brahmino", "hobopeeba",
        "meryvachon", "georgiarose_hardy", "nois7",
        "ericpare", "zachallia", "omarzrobles",
        "mattcrump", "mikekus", "pfruhan",
        "kateclarkephoto", "alexstrohl", "samuelelkins",
        "lennartpagel", "ruedeadam", "joshuamorin",
        "sfrutteroephoto", "bennyharlem", "shotbyriley",
        "taylormichaelburk", "zachallia",
    ],
}

# Flatten for backward compat (all accounts)
INSTAGRAM_USERNAMES = []
for tier_accounts in INSTAGRAM_TIERS.values():
    INSTAGRAM_USERNAMES.extend(tier_accounts)

# No validation — this is a real-image evaluation set
EXPECTED_FORMATS = ["JPEG", "PNG", "WEBP"]
MIN_PIXELS = 200_000
MAX_PIXELS = 50_000_000
KNOWN_ASPECT_RATIOS = [(1, 1), (4, 5), (5, 4), (16, 9), (9, 16), (3, 4), (4, 3), (3, 2), (2, 3)]
ASPECT_RATIO_TOLERANCE = 0.15
