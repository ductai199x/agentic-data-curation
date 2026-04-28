"""Shared video taxonomy constants — single source of truth.

Mirrors `docs/VIDEO_TAXONOMY.md`. Import from here anywhere in `video_gen/`
so label names stay consistent across labeler, ranker, and per-generator
selection logic.
"""

from __future__ import annotations

# ----------------------------------------------------------------------------
# Content categories (C1-C21)
# ----------------------------------------------------------------------------
CONTENT: list[tuple[str, str]] = [
    ("C1",  "People — casual (walking, sitting, social, candid)"),
    ("C2",  "People — action (sports, dancing, fitness, fighting)"),
    ("C3",  "Talking head (interviews, podcasts, vlogs, news anchors, video calls) — tight framing, chest-up, often static camera"),
    ("C4",  "Lecture (university lectures, conference talks, classroom, whiteboard) — wider than talking head, lecturer moves"),
    ("C5",  "Nature — landscape (mountains, forests, fields, desert, sky)"),
    ("C6",  "Nature — wildlife (animals in the wild, birds, marine life)"),
    ("C7",  "Nature — water (ocean, rivers, rain, waterfalls, underwater)"),
    ("C8",  "Walking/biking tour (city walks, bike rides, market walks, nature trails, real-time POV)"),
    ("C9",  "Urban — street (pedestrians, traffic, storefronts, markets)"),
    ("C10", "Urban — architecture (buildings, interiors, skylines)"),
    ("C11", "Vehicles — exterior (cars, bikes, trains, boats, planes seen from outside)"),
    ("C12", "Vehicles — POV (dashcam, cycling POV, cockpit — view from inside a moving vehicle)"),
    ("C13", "Cooking (home cooking, pro kitchen, outdoor/campfire, recipe demos)"),
    ("C14", "Product review (phones, cameras, electronics, fashion, unboxing, hands-on)"),
    ("C15", "Animals — domestic (pets, farm animals, zoo)"),
    ("C16", "Hands & objects (crafts, tools, instruments, writing, repair, close-up manipulation)"),
    ("C17", "Aerial/drone (landscapes, cities, beaches seen from above)"),
    ("C18", "Weather & atmosphere (storms, fog, snow, sunrise/sunset, clouds)"),
    ("C19", "Macro & texture (insects, water drops, fabric, fire, smoke, extreme close-up)"),
    ("C20", "Security camera (parking lots, streets, stores, homes — fixed elevated angle, often night/IR)"),
    ("C21", "Indoor — everyday (home, office, classroom, gym, shop — no specific activity focus)"),
]

# ----------------------------------------------------------------------------
# Motion types (M1-M11)
# ----------------------------------------------------------------------------
MOTION: list[tuple[str, str]] = [
    ("M1",  "Static / tripod — locked-off camera, only the subject moves"),
    ("M2",  "Handheld — stable (casual phone/camera, mild natural shake)"),
    ("M3",  "Handheld — shaky (running, walking, chaotic, visible jitter)"),
    ("M4",  "Gimbal / smooth tracking (stabilized follow shots)"),
    ("M5",  "Pan / tilt (deliberate camera rotation, sweeping across a scene)"),
    ("M6",  "Fast action (sports, vehicles, impacts, rapid movement)"),
    ("M7",  "Slow motion (120fps+, temporal stretching of fast events)"),
    ("M8",  "Timelapse / hyperlapse (compressed time, clouds sped up, construction)"),
    ("M9",  "Drone / aerial movement (orbit, flyover, reveal shots from above)"),
    ("M10", "Zoom (optical or digital zoom happening within the clip)"),
    ("M11", "Dolly / slide (linear camera translation, product shots, cinema)"),
]

# ----------------------------------------------------------------------------
# Camera types (K1-K9) — kept here for future use; not labeled from text alone
# ----------------------------------------------------------------------------
CAMERA: list[tuple[str, str]] = [
    ("K1", "Modern smartphone"),
    ("K2", "DSLR / mirrorless"),
    ("K3", "Action camera (GoPro, Insta360)"),
    ("K4", "Drone"),
    ("K5", "Dashcam"),
    ("K6", "Webcam / video call"),
    ("K7", "Security / CCTV"),
    ("K8", "Cinema / professional"),
    ("K9", "Vintage / older phone"),
]


CONTENT_IDS = [c[0] for c in CONTENT]
MOTION_IDS = [m[0] for m in MOTION]
CAMERA_IDS = [k[0] for k in CAMERA]


def format_taxonomy_prompt() -> str:
    """Build the enum list the LLM classifier sees as part of its system prompt."""
    content_lines = "\n".join(f"- {cid}: {desc}" for cid, desc in CONTENT)
    motion_lines = "\n".join(f"- {mid}: {desc}" for mid, desc in MOTION)
    return (
        "CONTENT CATEGORIES:\n"
        f"{content_lines}\n\n"
        "MOTION TYPES:\n"
        f"{motion_lines}"
    )


def is_valid_content(label: str) -> bool:
    return label in CONTENT_IDS


def is_valid_motion(label: str) -> bool:
    return label in MOTION_IDS
