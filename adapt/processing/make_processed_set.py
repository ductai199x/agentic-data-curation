# Builds the processed benchmark set: every base image/video x every transform in transforms.json.
# Usage: python3 make_processed_set.py --input_dir base/ --output_dir processed/ [--config transforms.json] [--workers 4]
import argparse, hashlib, json, os, random, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageFilter

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}

def sha256_of_file(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1 << 20), b""): hasher.update(chunk)
    return hasher.hexdigest()

# ---------- image ops (each takes and returns a PIL RGB image, except encode ops which round-trip bytes) ----------
def resize_long_side(image, long_side, upscale=False, resample="lanczos"):
    width, height = image.size
    scale = long_side / max(width, height)
    if scale >= 1 and not upscale: return image
    filters = {"lanczos": Image.LANCZOS, "bilinear": Image.BILINEAR, "bicubic": Image.BICUBIC}
    return image.resize((max(1, round(width * scale)), max(1, round(height * scale))), filters[resample])

def resize_short_side(image, short_side, upscale=False, resample="lanczos"):
    width, height = image.size
    return resize_long_side(image, round(max(width, height) * short_side / min(width, height)), upscale, resample)

def resize_max_width(image, max_width, resample="lanczos"):
    width, height = image.size
    return image if width <= max_width else resize_long_side(image, round(max(width, height) * max_width / width), resample=resample)

def resize_max_height(image, max_height, resample="lanczos"):
    width, height = image.size
    return image if height <= max_height else resize_long_side(image, round(max(width, height) * max_height / height), resample=resample)

def set_width(image, width, resample="lanczos"):
    # Display-style fit to a screen width (may upscale), as a phone renders an image before a screenshot
    old_width, old_height = image.size
    filters = {"lanczos": Image.LANCZOS, "bilinear": Image.BILINEAR, "bicubic": Image.BICUBIC}
    return image.resize((width, max(1, round(old_height * width / old_width))), filters[resample])

def scale_by(image, factor, resample="bilinear"):
    filters = {"lanczos": Image.LANCZOS, "bilinear": Image.BILINEAR, "bicubic": Image.BICUBIC, "nearest": Image.NEAREST}
    width, height = image.size
    return image.resize((max(1, round(width * factor)), max(1, round(height * factor))), filters[resample])

def center_crop_fraction(image, fraction):
    width, height = image.size
    crop_w, crop_h = round(width * fraction), round(height * fraction)
    left, top = (width - crop_w) // 2, (height - crop_h) // 2
    return image.crop((left, top, left + crop_w, top + crop_h))

def crop_to_aspect(image, aspect_w, aspect_h):
    width, height = image.size
    target = aspect_w / aspect_h
    if width / height > target:
        new_w = round(height * target); left = (width - new_w) // 2
        return image.crop((left, 0, left + new_w, height))
    new_h = round(width / target); top = (height - new_h) // 2
    return image.crop((0, top, width, top + new_h))

def random_crop_fraction(image, fraction, seed):
    width, height = image.size
    rng = random.Random(seed)
    crop_w, crop_h = round(width * fraction), round(height * fraction)
    left, top = rng.randint(0, width - crop_w), rng.randint(0, height - crop_h)
    return image.crop((left, top, left + crop_w, top + crop_h))

def encode_roundtrip(image, fmt, quality=None, subsampling=None):
    # Encode to bytes and decode back so later ops see real compression artifacts; metadata is dropped (platforms strip it)
    buffer = BytesIO()
    save_kwargs = {}
    if fmt == "JPEG":
        save_kwargs = {"quality": quality, "subsampling": {"444": 0, "422": 1, "420": 2}[subsampling or "420"], "optimize": True}
    elif fmt in ("WEBP", "AVIF"): save_kwargs = {"quality": quality}
    image.save(buffer, fmt, **save_kwargs)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB"), buffer.getvalue()

def gaussian_blur(image, radius): return image.filter(ImageFilter.GaussianBlur(radius))
def unsharp(image, radius=1.0, percent=80, threshold=2): return image.filter(ImageFilter.UnsharpMask(radius, percent, threshold))

def add_screenshot_frame(image, top_bar_px=96, bottom_bar_px=64, bar_gray=245):
    # Pads with flat UI-like bars, as a phone screenshot of a feed would
    width, height = image.size
    canvas = Image.new("RGB", (width, height + top_bar_px + bottom_bar_px), (bar_gray,) * 3)
    canvas.paste(image, (0, top_bar_px))
    return canvas

def apply_image_steps(image, steps, seed):
    final_format, final_bytes = "PNG", None
    for step in steps:
        op, params = step["op"], {k: v for k, v in step.items() if k != "op"}
        if op == "resize_long_side": image = resize_long_side(image, **params)
        elif op == "resize_short_side": image = resize_short_side(image, **params)
        elif op == "resize_max_width": image = resize_max_width(image, **params)
        elif op == "resize_max_height": image = resize_max_height(image, **params)
        elif op == "set_width": image = set_width(image, **params)
        elif op == "scale_by": image = scale_by(image, **params)
        elif op == "center_crop_fraction": image = center_crop_fraction(image, **params)
        elif op == "random_crop_fraction": image = random_crop_fraction(image, seed=seed, **params)
        elif op == "crop_to_aspect": image = crop_to_aspect(image, **params)
        elif op == "gaussian_blur": image = gaussian_blur(image, **params)
        elif op == "unsharp": image = unsharp(image, **params)
        elif op == "screenshot_frame": image = add_screenshot_frame(image, **params)
        elif op == "encode":
            image, final_bytes = encode_roundtrip(image, **params); final_format = params["fmt"]
        else: raise ValueError(f"unknown image op {op}")
    if final_bytes is None: image, final_bytes = encode_roundtrip(image, "PNG"); final_format = "PNG"
    return final_bytes, final_format

def process_one_image(job):
    source_path, transform, output_dir = job
    image = Image.open(source_path).convert("RGB")
    seed = int(hashlib.md5(f"{source_path.name}:{transform['name']}".encode()).hexdigest()[:8], 16)
    output_bytes, output_format = apply_image_steps(image, transform["steps"], seed)
    extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "AVIF": ".avif"}[output_format]
    output_path = output_dir / transform["name"] / (source_path.stem + extension)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output_bytes)
    with Image.open(output_path) as written: size = written.size
    return {"source": str(source_path), "transform": transform["name"], "family": transform.get("family", ""),
            "output": str(output_path), "sha256": sha256_of_file(output_path), "width": size[0], "height": size[1],
            "bytes": len(output_bytes)}

# ---------- video ops: each transform is an ffmpeg filter chain + encoder settings, optionally chained ----------
def build_ffmpeg_command(source_path, output_path, stage):
    filters = []
    if "crop_to_aspect" in stage:
        aw, ah = stage["crop_to_aspect"]
        filters.append(f"crop='if(gt(iw/ih,{aw}/{ah}),trunc(ih*{aw}/{ah}/2)*2,iw)':'if(gt(iw/ih,{aw}/{ah}),ih,trunc(iw*{ah}/{aw}/2)*2)'")
    if "pad_to_aspect" in stage:  # letterbox, e.g. landscape video posted to a 9:16 feed
        aw, ah = stage["pad_to_aspect"]
        filters.append(f"pad='trunc(max(iw,ih*{aw}/{ah})/2)*2':'trunc(max(ih,iw*{ah}/{aw})/2)*2':(ow-iw)/2:(oh-ih)/2:black")
    if "max_short_side" in stage:  # scale so short side <= value, keep aspect, even dims
        s = stage["max_short_side"]
        filters.append(f"scale='if(lt(iw,ih),min({s},iw),-2)':'if(lt(iw,ih),-2,min({s},ih))':flags={stage.get('scaler','bicubic')}")
    if "max_long_side" in stage:
        s = stage["max_long_side"]
        filters.append(f"scale='if(gte(iw,ih),min({s},iw),-2)':'if(gte(iw,ih),-2,min({s},ih))':flags={stage.get('scaler','bicubic')}")
    if "fps" in stage: filters.append(f"fps={stage['fps']}")
    filters.append("format=yuv420p")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source_path)]
    if "max_seconds" in stage: command += ["-t", str(stage["max_seconds"])]
    command += ["-vf", ",".join(filters), "-c:v", stage.get("codec", "libx264")]
    if "crf" in stage: command += ["-crf", str(stage["crf"])]
    if stage.get("bitrate_kbps") == 0: command += ["-b:v", "0"]  # VP9 constant-quality mode
    elif "bitrate_kbps" in stage:
        b = stage["bitrate_kbps"]
        command += ["-b:v", f"{b}k", "-maxrate", f"{int(b*1.5)}k", "-bufsize", f"{b*2}k"]
    if stage.get("codec", "libx264") in ("libx264", "libx265"): command += ["-preset", stage.get("preset", "medium")]
    if stage.get("codec") == "libvpx-vp9": command += ["-row-mt", "1", "-deadline", "good", "-cpu-used", "4"]
    if "gop" in stage: command += ["-g", str(stage["gop"])]
    command += ["-c:a", "aac", "-b:a", "128k", "-map_metadata", "-1", "-movflags", "+faststart", str(output_path)]
    return command

def process_one_video(job):
    source_path, transform, output_dir = job
    output_path = output_dir / transform["name"] / (source_path.stem + ".mp4")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    current_input = source_path
    for stage_index, stage in enumerate(transform["stages"]):
        is_last = stage_index == len(transform["stages"]) - 1
        stage_output = output_path if is_last else output_path.with_suffix(f".stage{stage_index}.mp4")
        subprocess.run(build_ffmpeg_command(current_input, stage_output, stage), check=True)
        if current_input != source_path: os.remove(current_input)
        current_input = stage_output
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height,codec_name,bit_rate,r_frame_rate", "-of", "json", str(output_path)],
        capture_output=True, text=True, check=True).stdout)["streams"][0]
    return {"source": str(source_path), "transform": transform["name"], "family": transform.get("family", ""),
            "output": str(output_path), "sha256": sha256_of_file(output_path), "width": probe["width"],
            "height": probe["height"], "codec": probe["codec_name"], "bit_rate": probe.get("bit_rate"),
            "bytes": output_path.stat().st_size}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_dir", required=True, type=Path)
    parser.add_argument("--output_dir", required=True, type=Path)
    parser.add_argument("--config", default=Path(__file__).with_name("transforms.json"), type=Path)
    parser.add_argument("--workers", default=os.cpu_count(), type=int)
    parser.add_argument("--only", nargs="*", help="transform names to run (default all)")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    selected = lambda transforms: [t for t in transforms if not args.only or t["name"] in args.only]
    sources = sorted(p for p in args.input_dir.rglob("*") if p.is_file())
    image_jobs = [(p, t, args.output_dir / "images") for p in sources if p.suffix.lower() in IMAGE_EXTENSIONS for t in selected(config["image_transforms"])]
    video_jobs = [(p, t, args.output_dir / "videos") for p in sources if p.suffix.lower() in VIDEO_EXTENSIONS for t in selected(config["video_transforms"])]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "manifest.jsonl"
    with ProcessPoolExecutor(args.workers) as pool, open(manifest_path, "a") as manifest:
        for job_list, worker in ((image_jobs, process_one_image), (video_jobs, process_one_video)):
            for record in pool.map(worker, job_list, chunksize=4):
                manifest.write(json.dumps(record) + "\n")
    print(f"{len(image_jobs)} image and {len(video_jobs)} video outputs -> {manifest_path}", file=sys.stderr)

if __name__ == "__main__": main()
