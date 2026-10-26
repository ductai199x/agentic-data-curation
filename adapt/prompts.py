"""Diverse, deterministic prompts for open-weights generation.

Prompts are compositional (subject x setting x lighting x camera) so a few hundred samples cover the content
a detector sees in the wild, with an emphasis on newsworthy, misinformation-prone scenes. Same seed -> same list,
so a resumed run regenerates nothing.
"""

import random

PHOTO_SUBJECTS = {
    "portrait": ["an elderly fisherman", "a young nurse in scrubs", "a teenage skateboarder", "a businesswoman on a phone call",
                 "a farmer holding a basket of tomatoes", "a street musician playing violin", "a firefighter after a shift",
                 "a grandmother laughing", "a student studying in a library", "a chef plating a dish"],
    "group": ["a crowd at a political rally holding signs", "protesters marching down a city avenue", "a family at a dinner table",
              "friends at a rooftop party", "commuters on a crowded subway platform", "a press conference with reporters",
              "volunteers distributing food after a flood", "fans celebrating in a stadium"],
    "news_scene": ["a flooded residential street with stranded cars", "a wildfire burning on a hillside near houses",
                   "a collapsed building after an earthquake with rescue workers", "police officers at a night-time traffic stop",
                   "a long line of voters outside a polling station", "a damaged bridge after a storm",
                   "smoke rising over an industrial district", "an empty supermarket shelf during a shortage"],
    "place": ["a narrow alley in an old European town", "a busy night market in Southeast Asia", "a quiet suburban cul-de-sac",
              "a modern open-plan office", "a cluttered teenager's bedroom", "a hospital corridor", "a rural gas station at dusk",
              "a snowy mountain village", "a desert highway", "a tropical beach at low tide"],
    "object": ["a bowl of ramen on a wooden table", "a vintage film camera on a shelf", "a smartphone lying on a car seat",
               "a stack of unpaid bills on a kitchen counter", "running shoes on a gym floor", "a bouquet of wildflowers in a jar",
               "a cup of coffee next to a laptop", "a handwritten letter and an envelope"],
    "animal": ["a golden retriever catching a frisbee", "a tabby cat sleeping on a windowsill", "a red fox in fresh snow",
               "a herd of elephants at a watering hole", "a pigeon on a city statue", "a horse in a misty field"],
    "vehicle": ["a delivery van double-parked in traffic", "a vintage motorcycle outside a cafe", "a freight train crossing a plain",
                "an electric car charging in a parking garage", "a small fishing boat in a harbor"],
}
SETTINGS_EXTRA = ["", "in the rain", "at golden hour", "on an overcast afternoon", "at night under streetlights",
                  "in harsh midday sun", "in winter", "during a festival"]
LIGHTING = ["natural light", "soft window light", "mixed fluorescent lighting", "flash photography", "backlit", "neon light"]
CAMERA = ["shot on a smartphone", "35mm photo", "DSLR, 85mm lens, shallow depth of field", "wide-angle shot",
          "candid snapshot", "drone photo from above", "security camera still", "photojournalism style"]
ART_STYLES = ["digital illustration", "oil painting", "watercolor", "3D render", "anime style", "pencil sketch",
              "flat vector poster", "concept art"]


def make_prompts(n: int, seed: str, mix: dict[str, float] | None = None) -> list[dict]:
    mix = mix or {"photo": 0.8, "art": 0.2}
    rng = random.Random(seed)
    categories = list(PHOTO_SUBJECTS)
    prompts = []
    for index in range(n):
        category = categories[index % len(categories)]  # round-robin keeps categories balanced
        subject = rng.choice(PHOTO_SUBJECTS[category])
        extra = rng.choice(SETTINGS_EXTRA)
        if rng.random() < mix.get("photo", 0.8):
            style, text = "photo", ", ".join(p for p in [f"{subject} {extra}".strip(), rng.choice(LIGHTING), rng.choice(CAMERA)] if p)
        else:
            style = rng.choice(ART_STYLES)
            text = f"{subject} {extra}, {style}".replace("  ", " ")
        prompts.append({"index": index, "prompt": text, "category": category, "style": style, "seed": rng.randrange(2**31)})
    return prompts
