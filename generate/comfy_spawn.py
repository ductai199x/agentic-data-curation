"""Self-contained ComfyUI spawner.

Used by `generate.comfy_batch_run` so each worker is responsible for its
own ComfyUI instance. No need to manually start / track external ComfyUI
servers on specific ports.

Key properties:
  * Random free port per spawn (no port-contention between workers)
  * Die-with-parent on Linux via prctl(PR_SET_PDEATHSIG, SIGKILL) — if the
    batch worker crashes or exits, the child ComfyUI is killed by the
    kernel automatically. atexit handler as a fallback.
  * `cpu_only=True` passes `--cpu` to ComfyUI (for pure API-proxy workers
    that don't need a GPU); otherwise the child inherits the parent's
    CUDA_VISIBLE_DEVICES so it uses the worker's assigned GPU.
  * Stdout+stderr redirected to `/tmp/comfy_batch_spawn/<pid>_port<port>.log`
    so boot failures are debuggable (otherwise "comfy never came up" gives
    no clue why).
"""
from __future__ import annotations

import atexit
import ctypes
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path


def _find_free_port() -> int:
    """Ask the kernel for a free TCP port on 127.0.0.1 and release it.

    Small race window between close and child bind, but irrelevant for
    single-user dev where port churn is low.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _die_with_parent():
    """preexec_fn: kernel sends SIGKILL to this child when parent exits.

    Linux-only (prctl PR_SET_PDEATHSIG=1). No-op on platforms without prctl.
    """
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL)
    except Exception:
        pass


def spawn_comfy(comfy_root: Path, cpu_only: bool = False) -> tuple[subprocess.Popen, int]:
    """Spawn a dedicated ComfyUI instance.

    Args:
      comfy_root: Path to the ComfyUI repo (with `main.py` and `.venv`).
      cpu_only:   Pass `--cpu` (for pure API-proxy workers). GPU workers
                  like Wan 2.2 / LTX leave this False so ComfyUI uses the
                  parent-set CUDA_VISIBLE_DEVICES.

    Returns (process, port). Child is registered for die-with-parent.
    """
    port = _find_free_port()
    python = comfy_root / ".venv" / "bin" / "python"
    main_py = comfy_root / "main.py"
    log_dir = Path("/tmp") / "comfy_batch_spawn"
    log_dir.mkdir(exist_ok=True)
    err_log = log_dir / f"{os.getpid()}_port{port}.log"
    err_fp = open(err_log, "w")

    cmd = [str(python), str(main_py),
           "--listen", "127.0.0.1", "--port", str(port),
           "--disable-auto-launch"]
    if cpu_only:
        cmd.append("--cpu")

    proc = subprocess.Popen(
        cmd,
        cwd=str(comfy_root),
        preexec_fn=_die_with_parent,
        stdout=err_fp,
        stderr=subprocess.STDOUT,
    )

    def _cleanup():
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            err_fp.close()
        except Exception:
            pass

    atexit.register(_cleanup)
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    print(f"[spawn_comfy] pid={proc.pid} port={port} cpu={cpu_only} log={err_log}", flush=True)
    return proc, port
