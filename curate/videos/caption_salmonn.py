"""Caption real video clips with video-SALMONN 2+ 7B (audio-aware).

Produces the `video_captions.json` files that condition fake-video generation
in `generate.comfy_batch_run`. Mirrors the ComfyUI integration pattern:

  third_party/SALMONN-2-plus/    →   third_party/ComfyUI/
  scripts/launch_caption.sh      →   scripts/launch.sh
  curate/videos/caption_salmonn  →   generate/comfy_batch_run
  qwenvl modules (sys.path)      →   ComfyUI HTTP API

The qwenvl + flash-attn + liger_kernel deps live ONLY in the SALMONN venv at
`third_party/SALMONN-2-plus/.venv/`. Launch via `scripts/launch_caption.sh`
(uses that venv's python) — running with the project venv will fail at
import time.

CLI:
    curate videos caption-salmonn --videos-dir data/videos/real/youtube/validated \\
        --output data/videos/real/youtube/video_captions.json --shards 8 --shard-id 0

Or directly per-shard:
    PYTHONPATH=$REPO/third_party/SALMONN-2-plus:$REPO \\
      $REPO/third_party/SALMONN-2-plus/.venv/bin/python \\
      -m curate.videos.caption_salmonn --videos-dir ... --shards 8 --shard-id 0
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click

from shared.paths import REPO_ROOT


SALMONN_DIR = REPO_ROOT / "third_party" / "SALMONN-2-plus"
if str(SALMONN_DIR) not in sys.path:
    sys.path.insert(0, str(SALMONN_DIR))


DEFAULT_MODEL = "tsinghua-ee/video-SALMONN2_plus_7B_full"

DEFAULT_PROMPT = (
    "<video>\n"
    "Provide a comprehensive description of all the content in the video, "
    "leaving out no details. Be sure to include as much of the audio information "
    "as possible, and ensure that your descriptions of the audio and video are "
    "closely aligned."
)


def _apply_liger_kernel():
    from liger_kernel.transformers.qwen2vl_mrope import liger_multimodal_rotary_pos_emb
    from liger_kernel.transformers.rms_norm import LigerRMSNorm
    from liger_kernel.transformers.swiglu import LigerSwiGLUMLP
    from qwenvl.model import modeling_qwen2_5_vl
    modeling_qwen2_5_vl.apply_multimodal_rotary_pos_emb = liger_multimodal_rotary_pos_emb
    modeling_qwen2_5_vl.Qwen2RMSNorm = LigerRMSNorm
    modeling_qwen2_5_vl.Qwen2MLP = LigerSwiGLUMLP


def load_model(model_path: str):
    """Load SALMONN model + tokenizer + dataset preprocessor.

    Imports are lazy so `--help` works under the project venv (which lacks
    torch + qwenvl); only running actually requires the SALMONN venv.
    """
    import torch
    from qwenvl.model.modeling_qwen2_5_vl import video_SALMONN2_plus
    from qwenvl.data.dataset import make_supervised_data_module
    from qwenvl.data.image_processing_qwen2_vl_fast import Qwen2VLImageProcessorFast
    from qwenvl.train.argument import DataArguments
    from transformers import AutoTokenizer, WhisperFeatureExtractor

    _apply_liger_kernel()

    data_args = DataArguments()
    data_args.video_max_frames = 768
    data_args.video_min_frames = 16
    data_args.base_interval = 0.1
    data_args.max_pixels = 61250
    data_args.video_max_frame_pixels = 61250
    data_args.run_test = True
    data_args.image_processor = Qwen2VLImageProcessorFast.from_pretrained(model_path)
    data_args.audio_processor = WhisperFeatureExtractor(
        feature_size=data_args.feature_size,
        sampling_rate=data_args.sampling_rate,
        hop_length=data_args.hop_length,
        chunk_length=data_args.chunk_length,
    )
    data_args.model_type = "qwen2.5vl"

    tokenizer = AutoTokenizer.from_pretrained(
        model_path, model_max_length=131072,
        padding_side="right", use_fast=False,
    )

    model = video_SALMONN2_plus.from_pretrained(
        model_path,
        attn_implementation="flash_attention_2",
        torch_dtype=torch.bfloat16,
        device_map="cpu",
    )
    model.cuda()
    model.eval()

    data_module = make_supervised_data_module(tokenizer=tokenizer, data_args=data_args)
    dataset = data_module["train_dataset"]

    return model, tokenizer, dataset


def _prepare_inputs(inputs):
    import torch
    for k in ("video", "image", "prompt", "ref", "audio", "use_audio", "should_use"):
        inputs.pop(k, None)
    return {
        k: v.to(f"cuda:{torch.cuda.current_device()}")
        for k, v in inputs.items() if isinstance(v, torch.Tensor)
    }


def _reencode_to_h264(src: str) -> str:
    """Re-encode a video to clean H264+AAC mp4 in /tmp. Returns new path."""
    import subprocess as sp
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", prefix="salmonn_reenc_", delete=False)
    tmp.close()
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", src,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        tmp.name,
    ]
    sp.run(cmd, check=True, timeout=120)
    return tmp.name


def _try_caption(path, model, tokenizer, dataset, prompt, use_audio, max_new_tokens):
    """One inference attempt. Raises on failure."""
    import torch
    input_dict = {
        "video": path,
        "use_audio": use_audio,
        "conversations": [
            {"from": "human", "value": prompt},
            {"from": "gpt", "value": ""},
        ],
    }
    inputs = dataset._get_item(input_dict)
    if inputs is None:
        raise RuntimeError("dataset._get_item returned None (decoder failure)")
    inputs = _prepare_inputs(inputs)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )
    trimmed = outputs[0, len(inputs["input_ids"][0]):]
    return tokenizer.decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)


def caption_video(video_path: str, model, tokenizer, dataset,
                  prompt: str = DEFAULT_PROMPT, use_audio: bool = True,
                  max_new_tokens: int = 1024) -> str:
    """Caption a video, with fallbacks for decoder failures.

    Order of attempts:
      1. Original file with audio
      2. Original file without audio
      3. Re-encoded file with audio
      4. Re-encoded file without audio
    """
    import os as _os

    attempts = [(False, use_audio)]
    if use_audio:
        attempts.append((False, False))
    attempts.append((True, use_audio))
    if use_audio:
        attempts.append((True, False))

    last_err = None
    reencoded_path = None
    try:
        for use_reenc, audio_flag in attempts:
            try:
                if use_reenc and reencoded_path is None:
                    reencoded_path = _reencode_to_h264(video_path)
                path = reencoded_path if use_reenc else video_path
                return _try_caption(
                    path, model, tokenizer, dataset, prompt, audio_flag, max_new_tokens,
                )
            except Exception as e:
                last_err = e
    finally:
        if reencoded_path and reencoded_path.startswith("/tmp/salmonn_reenc_"):
            try:
                _os.unlink(reencoded_path)
            except Exception:
                pass

    raise RuntimeError(f"all caption attempts failed; last error: {last_err}")


def _load_existing(output_path: Path) -> dict:
    """Load existing captions from THIS shard's output file for resume."""
    if output_path.exists():
        try:
            return json.load(open(output_path))
        except Exception:
            return {}
    return {}


def _load_all_processed(output_dir: Path, stem: str) -> set:
    """Load processed filenames from ALL shard outputs to dedupe across workers."""
    processed = set()
    for f in output_dir.glob(f"{stem}*.json"):
        try:
            data = json.load(open(f))
            processed.update(data.keys())
        except Exception:
            pass
    return processed


@click.command()
@click.option("--model", default=DEFAULT_MODEL, show_default=True,
              help="HuggingFace model path or local checkpoint dir.")
@click.option("--videos", multiple=True, type=click.Path(exists=True, dir_okay=False),
              help="Explicit video paths (repeatable). Combine with or replace --videos-dir.")
@click.option("--videos-dir", type=click.Path(exists=True, file_okay=False),
              help="Directory of videos to caption.")
@click.option("--limit", type=int, default=0,
              help="Only caption first N videos from --videos-dir (0=all).")
@click.option("--output", required=True, type=click.Path(),
              help="Output JSON. With --shards, '_shard{id}' is appended before extension.")
@click.option("--no-audio", is_flag=True, help="Visual-only mode (skip audio token attention).")
@click.option("--max-new-tokens", type=int, default=1024, show_default=True)
@click.option("--shards", type=int, default=1, show_default=True,
              help="Total worker shards (use scripts/launch_caption.sh for multi-GPU launch).")
@click.option("--shard-id", type=int, default=0, show_default=True,
              help="This worker's shard ID (0-indexed). Set CUDA_VISIBLE_DEVICES externally.")
@click.option("--save-every", type=int, default=5, show_default=True,
              help="Persist incremental output every N clips.")
def main(model: str, videos: tuple[str, ...], videos_dir: str | None,
         limit: int, output: str, no_audio: bool, max_new_tokens: int,
         shards: int, shard_id: int, save_every: int):
    """Caption videos with video-SALMONN 2+ 7B."""
    # Collect videos
    video_paths: list[str] = list(videos)
    if videos_dir:
        d = Path(videos_dir)
        found = sorted(str(f) for f in d.iterdir()
                       if f.suffix.lower() in (".mp4", ".webm", ".mkv", ".mov"))
        if limit:
            found = found[:limit]
        video_paths.extend(found)
    if not video_paths:
        click.echo("No videos given. Use --videos or --videos-dir.", err=True)
        sys.exit(1)

    # Shard partitioning (every Nth video to this worker)
    if shards > 1:
        video_paths = [v for i, v in enumerate(video_paths) if i % shards == shard_id]

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if shards > 1:
        out_path = out_path.parent / f"{out_path.stem}_shard{shard_id}{out_path.suffix}"

    # Resume: this shard's existing rows + dedupe against ALL shards' outputs
    results = _load_existing(out_path)
    out_stem = Path(output).stem
    out_dir = Path(output).parent or Path(".")
    processed_all = _load_all_processed(out_dir, out_stem)

    remaining = [v for v in video_paths if Path(v).name not in processed_all]
    tag = f"shard {shard_id}/{shards}" if shards > 1 else "single"
    print(f"[{tag}] total={len(video_paths)} done={len(video_paths) - len(remaining)} "
          f"remaining={len(remaining)}", flush=True)

    if not remaining:
        print("Nothing to do.")
        return

    print(f"Loading {model}...", flush=True)
    t0 = time.time()
    mdl, tok, ds = load_model(model)
    print(f"Loaded in {time.time() - t0:.1f}s", flush=True)

    use_audio = not no_audio
    for i, vp in enumerate(remaining):
        print(f"\n[{tag} {i+1}/{len(remaining)}] {Path(vp).name}", flush=True)
        t0 = time.time()
        try:
            caption = caption_video(
                vp, mdl, tok, ds,
                use_audio=use_audio,
                max_new_tokens=max_new_tokens,
            )
            elapsed = time.time() - t0
            print(f"  [{elapsed:.1f}s] {caption[:200]}{'...' if len(caption) > 200 else ''}",
                  flush=True)
            results[Path(vp).name] = {
                "caption": caption,
                "video_path": vp,
                "elapsed_s": round(elapsed, 2),
                "use_audio": use_audio,
            }
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)
            results[Path(vp).name] = {"error": str(e), "video_path": vp}

        if (i + 1) % save_every == 0 or (i + 1) == len(remaining):
            with open(out_path, "w") as f:
                json.dump(results, f, indent=2)

    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[{tag}] Saved {len(results)} captions to {out_path}")


if __name__ == "__main__":
    main()
