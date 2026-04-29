"""Generic batch worker — drives a ComfyUI instance over HTTP.

Every worker is self-contained: spawns its own ComfyUI child on a random
free port via `generate.comfy_spawn`, runs its shard of jobs, writes one
manifest row per clip. Works for any generator — the workflow is built by
the module named in `cfg.workflow_module` (see `ComfyRunConfig`).

Launch via `scripts/launch.sh`:
    COMFY_CONFIG=configs.generate.wan22_instagram scripts/launch.sh start

Or directly for one shard:
    PYTHONPATH=. CUDA_VISIBLE_DEVICES=0 COMFY_CONFIG=configs.generate.wan22_instagram \\
        SHARDS=1 SHARD_ID=0 \\
        third_party/ComfyUI/.venv/bin/python -m generate.comfy_batch_run
"""

from __future__ import annotations

import csv
import importlib
import os
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from generate.comfy_config import ComfyRunConfig, load_config  # noqa: E402
from generate.common import build_jobs, shard_jobs  # noqa: E402
from generate.comfy_spawn import spawn_comfy as _spawn_comfy  # noqa: E402


# ---------------------------------------------------------------------------
# API key loader + credit balance query
# ---------------------------------------------------------------------------

COMFY_API_BASE = "https://api.comfy.org"


def load_api_key(cfg: ComfyRunConfig) -> str | None:
    """Return the comfy.org API key or None. Prefers env var, falls back to file."""
    key = os.environ.get(cfg.api_key_env, "").strip()
    if key:
        return key
    if cfg.api_key_file.exists():
        try:
            val = cfg.api_key_file.read_text().strip()
            return val or None
        except Exception:
            return None
    return None


def get_credit_balance(api_key: str) -> float:
    """Query comfy.org for the current credit balance.

    Returns balance in credits (not USD). Uses the undocumented but stable
    `GET /customers/balance` endpoint with `X-API-Key` header.
    The response field `effective_balance_micros` is actually in USD (despite
    the name), so we convert: credits = usd_balance * 211.
    """
    try:
        r = requests.get(
            f"{COMFY_API_BASE}/customers/balance",
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        # Field is named "micros" but actually contains USD cents
        cents = data.get("effective_balance_micros", 0)
        return round(cents / 100.0 * 211, 2)  # cents → USD → credits
    except Exception:
        return -1.0  # signal failure without crashing

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
MANIFEST_FIELDS = [
    "real_clip", "output_path", "first_frame",
    "prompt_preview", "duration_s", "status", "model",
    "elapsed_s", "actual_credits", "timestamp", "error",
]


def load_processed(manifest_path: Path) -> set[str]:
    if not manifest_path.exists():
        return set()
    done = set()
    with open(manifest_path) as f:
        for row in csv.DictReader(f):
            if row.get("real_clip") and row.get("status") in ("generated", "failed_permanent"):
                done.add(row["real_clip"])
    return done


def append_manifest(manifest_path: Path, row: dict):
    write_header = not manifest_path.exists()
    with open(manifest_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if write_header:
            w.writeheader()
        w.writerow(row)


# ---------------------------------------------------------------------------
# Comfy HTTP + Websocket client
# ---------------------------------------------------------------------------

def wait_for_comfy(session: requests.Session, server: str, retries: int = 60,
                   delay_s: float = 2.0) -> bool:
    for _ in range(retries):
        try:
            if session.get(f"{server}/system_stats", timeout=5).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(delay_s)
    return False


def _parse_ws_price(data: bytes) -> float | None:
    """Parse a binary websocket frame from ComfyUI for 'Price: X credits'.

    ComfyUI TEXT events (type=3): [4B event_type][4B node_id_len][node_id][text]
    The text may contain "Price: 168.8 credits" logged by API-Nodes after billing.
    """
    import struct
    if len(data) < 8:
        return None
    event_type = struct.unpack(">I", data[:4])[0]
    if event_type != 3:  # TEXT
        return None
    node_id_len = struct.unpack(">I", data[4:8])[0]
    text_start = 8 + node_id_len
    if text_start >= len(data):
        return None
    text = data[text_start:].decode("utf-8", errors="replace")
    if "Price:" not in text:
        return None
    try:
        price_str = text.split("Price:")[1].split("credits")[0].strip().replace(",", "")
        return float(price_str)
    except (ValueError, IndexError):
        return None


class SubmitResult:
    """Result of a submit_and_wait call, including actual credit cost."""
    __slots__ = ("output_path", "error", "actual_credits")

    def __init__(self, output_path: str | None, error: str, actual_credits: float):
        self.output_path = output_path
        self.error = error
        self.actual_credits = actual_credits


def submit_and_wait(session: requests.Session, server: str, workflow: dict,
                    timeout_s: float = 1800,
                    api_key: str | None = None,
                    comfy_output_dir: Path | None = None) -> SubmitResult:
    """Submit a workflow dict; poll /history/<id>; return SubmitResult.

    Connects a websocket to capture the real credit cost reported by
    ComfyUI's API-Nodes (sent as a binary TEXT event with 'Price: X credits').

    If `api_key` is provided, it's attached to the workflow's `extra_data` so
    ComfyUI's bundled API-Nodes (Runway/Veo/Kling/Hailuo/Pika/Luma/etc.) can
    bill outbound provider calls from the user's comfy.org credit balance.
    """
    import threading
    import websocket as _ws

    client_id = str(uuid.uuid4())
    captured_credits: list[float] = []

    # --- Websocket listener (background thread) ---
    ws_url = server.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/ws?clientId={client_id}"
    ws: _ws.WebSocket | None = None
    ws_stop = threading.Event()

    def _ws_listener():
        nonlocal ws
        try:
            ws = _ws.create_connection(ws_url, timeout=5)
            ws.settimeout(1.0)
            while not ws_stop.is_set():
                try:
                    _, data = ws.recv_data(control_frame=False)
                    if isinstance(data, (bytes, bytearray)):
                        price = _parse_ws_price(data)
                        if price is not None:
                            captured_credits.append(price)
                except _ws.WebSocketTimeoutException:
                    continue
                except Exception:
                    break
        except Exception:
            pass
        finally:
            if ws:
                try:
                    ws.close()
                except Exception:
                    pass

    ws_thread = threading.Thread(target=_ws_listener, daemon=True)
    ws_thread.start()

    # --- Submit via HTTP ---
    payload = {"prompt": workflow, "client_id": client_id}
    if api_key:
        payload["extra_data"] = {"api_key_comfy_org": api_key}
    r = session.post(f"{server}/prompt", json=payload, timeout=30)
    if r.status_code != 200:
        ws_stop.set()
        return SubmitResult(None, f"submit failed {r.status_code}: {r.text[:300]}", 0.0)
    prompt_id = r.json()["prompt_id"]

    # --- Poll /history + drain websocket ---
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(2)
        try:
            h = session.get(f"{server}/history/{prompt_id}", timeout=15).json()
        except Exception:
            continue
        if prompt_id not in h:
            continue
        entry = h[prompt_id]
        status = entry.get("status", {})
        actual = sum(captured_credits) if captured_credits else 0.0

        if status.get("completed"):
            ws_stop.set()
            # VHS_VideoCombine emits `gifs`; SaveVideo emits `images` with a video filename;
            # plain ImageSave emits `images`. Union of all possible shapes.
            save_node = entry.get("outputs", {}).get("save", {})
            outputs = (
                save_node.get("gifs")
                or save_node.get("videos")
                or save_node.get("images")
                or []
            )
            if outputs:
                o = outputs[0]
                fp = o.get("fullpath")
                if fp:
                    return SubmitResult(fp, "", actual)
                filename = o.get("filename")
                if not filename:
                    return SubmitResult(None, "completed but no filename in output", actual)
                subfolder = o.get("subfolder") or ""
                output_type = o.get("type") or "output"
                if comfy_output_dir is None:
                    return SubmitResult(filename, "", actual)
                base = comfy_output_dir.parent / output_type if comfy_output_dir.name == "output" and output_type != "output" else comfy_output_dir
                full = base / subfolder / filename if subfolder else base / filename
                return SubmitResult(str(full), "", actual)
            return SubmitResult(None, "completed but no output path", actual)
        if status.get("status_str") == "error":
            ws_stop.set()
            err_str = ""
            for m in status.get("messages", []):
                if m[0] == "execution_error":
                    err_str = m[1].get("exception_message", "")[:300]
            return SubmitResult(None, f"execution error: {err_str or 'unknown'}", actual)

    ws_stop.set()
    return SubmitResult(None, "timeout", sum(captured_credits) if captured_credits else 0.0)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main():
    config_module = os.environ.get("COMFY_CONFIG") or os.environ.get("WAN_CONFIG")
    if not config_module:
        print("set COMFY_CONFIG=<module> (e.g. configs.generate.wan22_instagram)", flush=True)
        sys.exit(1)
    cfg = load_config(config_module)

    shards = int(os.environ.get("SHARDS", "1"))
    shard_id = int(os.environ.get("SHARD_ID", "0"))

    # Two modes: use an externally-running ComfyUI (COMFY_PORT set), or spawn
    # a dedicated one bound to a random free port (default for commercial
    # API pilots so they don't queue behind local GPU jobs).
    _external_port = os.environ.get("COMFY_PORT")
    _spawned = None
    if _external_port:
        comfy_port = int(_external_port)
    else:
        # Commercial pilots are pure API proxies — pass --cpu so ComfyUI
        # doesn't try to init a GPU (would crash with CUDA_VISIBLE_DEVICES="").
        # Local GPU workflows (Wan 2.1 FLF, Hunyuan, CogVideoX, ...) need GPU
        # mode so ComfyUI can load models onto the parent's CUDA device.
        _spawned, comfy_port = _spawn_comfy(cfg.comfy_root, cpu_only=cfg.paid_provider)
        print(f"[shard {shard_id}/{shards}] spawned dedicated ComfyUI "
              f"pid={_spawned.pid} port={comfy_port} cpu={cfg.paid_provider}", flush=True)
    server = f"http://127.0.0.1:{comfy_port}"

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    comfy_input = cfg.comfy_root / "input"
    comfy_input.mkdir(exist_ok=True)

    def log(msg: str) -> None:
        print(f"[shard {shard_id}/{shards}] {msg}", flush=True)

    workflow_mod = importlib.import_module(cfg.workflow_module)
    if not hasattr(workflow_mod, "build_workflow"):
        log(f"workflow module '{cfg.workflow_module}' missing build_workflow()")
        sys.exit(1)

    log(f"config:    {config_module}")
    log(f"workflow:  {cfg.workflow_module}")
    log(f"model_tag: {cfg.model_tag}")
    log(f"comfy:     {server}")
    log(f"output:    {cfg.output_dir}")

    # ---- paid-provider safety gate -----------------------------------------
    api_key: str | None = None
    if cfg.paid_provider:
        api_key = load_api_key(cfg)
        if not api_key:
            log(
                f"paid_provider=True but no API key found in "
                f"${cfg.api_key_env} or {cfg.api_key_file} — refusing to start"
            )
            sys.exit(1)
        log(f"api_key_comfy_org=<set>  (len={len(api_key)}, source={'env' if os.environ.get(cfg.api_key_env) else 'file'})")

        if cfg.cost_per_clip_usd <= 0:
            log("cfg.cost_per_clip_usd not set for paid config — refusing")
            sys.exit(1)
        if cfg.max_cost_usd <= 0:
            log("cfg.max_cost_usd not set for paid config — refusing")
            sys.exit(1)

    dry_run = os.environ.get("COMFY_DRY_RUN", "").lower() in ("1", "true", "yes")
    if dry_run:
        log("DRY RUN MODE: will build workflows + print summary, no /prompt submits")

    log("building jobs...")
    jobs = build_jobs(
        cfg.clips_dir,
        cfg.captions_path,
        cfg.frames_dir,
        rank_file=cfg.rank_file,
        max_clips=cfg.max_clips,
        caption_key=cfg.prompt_source,
    )
    if cfg.rank_file:
        log(f"using rank file: {cfg.rank_file}")
    if cfg.max_clips:
        log(f"capped at max_clips={cfg.max_clips}")
    log(f"prompt_source={cfg.prompt_source}  prompt_max_chars={cfg.prompt_max_chars}")
    log(f"total jobs: {len(jobs)}")

    jobs = shard_jobs(jobs, shard_id, shards)
    log(f"my shard:   {len(jobs)} jobs")

    manifest_path = cfg.output_dir / (
        f"manifest_shard{shard_id}.csv" if shards > 1 else "manifest.csv"
    )
    processed = load_processed(manifest_path)
    remaining = [
        j for j in jobs
        if j.real_clip.name not in processed
        and not (cfg.output_dir / f"{j.real_clip.stem}.mp4").exists()
    ]
    log(f"already done: {len(jobs) - len(remaining)}")
    log(f"remaining:    {len(remaining)}")
    if not remaining:
        log("nothing to do")
        return

    # ---- hard budget gate (paid providers) --------------------------------
    if cfg.paid_provider:
        projected = len(remaining) * cfg.cost_per_clip_usd
        log(
            f"budget estimate: {len(remaining)} clips × ${cfg.cost_per_clip_usd:.4f} "
            f"= ${projected:.2f}  (ceiling: ${cfg.max_cost_usd:.2f})"
        )
        if projected > cfg.max_cost_usd:
            log(
                f"REFUSING: projected cost ${projected:.2f} exceeds ceiling "
                f"${cfg.max_cost_usd:.2f}. Lower max_clips or raise max_cost_usd."
            )
            sys.exit(1)

    if dry_run:
        for i, job in enumerate(remaining):
            log(f"[dry-run {i+1}/{len(remaining)}] {job.real_clip.stem}  prompt[:80]={job.prompt[:80]!r}")
        log("dry-run complete, no prompts submitted")
        return

    session = requests.Session()
    if not wait_for_comfy(session, server):
        log(f"comfy never came up on {server}, exiting")
        sys.exit(1)
    log("comfy ready")

    spent_usd = 0.0

    for i, job in enumerate(remaining):
        stem = job.real_clip.stem
        out_path = cfg.output_dir / f"{stem}.mp4"

        if out_path.exists():
            log(f"[{i+1}/{len(remaining)}] {stem}: already exists, skipping")
            continue

        # Running-total budget guard — stop before the next clip if it'd exceed
        if cfg.paid_provider:
            next_total = spent_usd + cfg.cost_per_clip_usd
            if next_total > cfg.max_cost_usd:
                log(
                    f"STOP: next clip would bring spend to ${next_total:.2f} > "
                    f"ceiling ${cfg.max_cost_usd:.2f}. Halting."
                )
                break

        # Real balance check — every 5 clips or when nearing budget, not every clip
        credits_before = -1.0
        if cfg.paid_provider and api_key and (i % 5 == 0 or spent_usd > cfg.max_cost_usd * 0.8):
            credits_before = get_credit_balance(api_key)
            if credits_before >= 0:
                min_required = cfg.cost_per_clip_usd * 211 * 2  # 2× buffer
                if credits_before < min_required:
                    log(
                        f"STOP: real balance {credits_before:.1f} credits "
                        f"< 2× clip cost ({min_required:.1f}). "
                        f"Top up before continuing."
                    )
                    break

        # Copy first + (optional) last frame into a per-provider subdir of
        # ComfyUI's input/ to prevent races with other batches (Wan 2.2 native
        # run, other pilots) that share the same input dir and delete files
        # after use. LoadImage accepts subfolder-prefixed paths via os.path.join.
        provider_subdir = cfg.model_tag.replace("/", "_")
        provider_dir = comfy_input / provider_subdir
        provider_dir.mkdir(exist_ok=True)
        first_name = f"{provider_subdir}/{stem}_first.png"
        last_name = f"{provider_subdir}/{stem}_last.png"
        first_dst = comfy_input / first_name
        last_dst = comfy_input / last_name
        # Always copy (overwrite) — defends against a prior run having deleted
        # the file or it being corrupted mid-copy by another worker.
        shutil.copy(job.first_frame, first_dst)
        if job.last_frame.exists():
            shutil.copy(job.last_frame, last_dst)

        filename_prefix = f"{cfg.model_tag}_shard{shard_id}_{stem}"
        prompt_text = job.prompt[: cfg.prompt_max_chars]

        log(f"[{i+1}/{len(remaining)}] {stem}")
        print(f"  prompt[:120]: {prompt_text[:120]!r}", flush=True)

        wf = workflow_mod.build_workflow(
            cfg=cfg,
            first_frame_name=first_name,
            last_frame_name=last_name if last_dst.exists() else None,
            prompt_text=prompt_text,
            filename_prefix=filename_prefix,
            first_frame_path=job.first_frame,
        )

        t0 = time.time()
        result = submit_and_wait(
            session, server, wf,
            timeout_s=cfg.submit_timeout_s,
            api_key=api_key,
            comfy_output_dir=cfg.comfy_root / "output",
        )
        elapsed = time.time() - t0

        status = "generated"
        error = ""
        provider_succeeded = False
        if result.output_path is None:
            status = "failed"
            error = result.error
            print(f"  ERROR: {error}", flush=True)
        else:
            provider_succeeded = True
            try:
                shutil.move(result.output_path, out_path)
            except Exception as e:
                status = "failed"
                error = f"move failed: {e}  (paid clip stranded at {result.output_path})"

        if status == "generated" and not out_path.exists():
            status = "failed"
            error = "pipeline finished but output missing"

        if cfg.delete_input_frame_after_use:
            for p in (first_dst, last_dst):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

        size_mb = out_path.stat().st_size / 1e6 if out_path.exists() else 0
        duration_s = round(
            cfg.model_kwargs.get("duration",
                cfg.model_kwargs.get("num_frames", 0) / max(cfg.model_kwargs.get("fps", 1), 1)),
            2,
        )
        # Per-clip spend uses the calibrated rate (cfg.cost_per_clip_usd),
        # period. Balance-diff was noisy when multiple pilots run in parallel
        # against the same comfy.org account — they each saw other pilots'
        # billing and double-counted. Calibration was done sequentially in
        # generate.calibrate_credits.py and its output is the source of
        # truth. The /customers/balance check below is kept as a standalone
        # hard-stop safety net against runaway charges.
        actual_credits = 0.0
        cost_source = "n/a"
        if cfg.paid_provider and provider_succeeded:
            actual_credits = cfg.cost_per_clip_usd * 211
            cost_source = "calibrated"

        if cfg.paid_provider:
            spent_usd += actual_credits / 211.0
            cost_tag = (
                f"  credits={actual_credits:.1f}({cost_source})"
                f"  spent=${spent_usd:.2f}/{cfg.max_cost_usd:.2f}"
            )
        else:
            cost_tag = ""
        print(f"  [{elapsed:.1f}s] {status} ({size_mb:.1f}MB){cost_tag}", flush=True)

        append_manifest(manifest_path, {
            "real_clip": job.real_clip.name,
            "output_path": str(out_path) if status == "generated" else "",
            "first_frame": str(job.first_frame),
            "prompt_preview": prompt_text[:200].replace("\n", " "),
            "duration_s": duration_s,
            "status": status,
            "model": cfg.model_tag,
            "elapsed_s": round(elapsed, 2),
            "actual_credits": round(actual_credits, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": error,
        })

    log("done.")


if __name__ == "__main__":
    main()
