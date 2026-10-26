"""Where Tai's training plugs in. The pipeline never guesses at training code; it only runs a command template.

ADAPT_TRAIN_CMD placeholders:
  {batch_dir} {manifest} {train_dir} {val_dir} {base_checkpoint} {output_dir} {generator} {run_id}
Contract: the command trains (or fine-tunes) from {base_checkpoint} on the batch, writes the new checkpoint under
{output_dir}, and exits 0. If {output_dir}/checkpoint.txt exists its first line is taken as the checkpoint path,
otherwise {output_dir} itself is. The new checkpoint is registered as model tag "<run_id>" and becomes current.
With no ADAPT_TRAIN_CMD, train hands back to Tai: run it however you like, then `adapt mark-trained`.
"""

import os
import subprocess
from pathlib import Path

from adapt.timeline import now_iso


def train_command(run_id: str, batch_dir: Path, base_checkpoint: str, output_dir: Path, generator: str) -> str | None:
    template = os.environ.get("ADAPT_TRAIN_CMD")
    if not template: return None
    return template.format(batch_dir=batch_dir, manifest=batch_dir / "manifest.csv", train_dir=batch_dir / "train",
                           val_dir=batch_dir / "val", base_checkpoint=base_checkpoint, output_dir=output_dir,
                           generator=generator, run_id=run_id)


def run_training(command: str, output_dir: Path, log_path: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as log:
        log.write(f"\n# {now_iso()} $ {command}\n"); log.flush()
        subprocess.run(command, shell=True, check=True, stdout=log, stderr=subprocess.STDOUT)
    pointer = output_dir / "checkpoint.txt"
    return pointer.read_text().splitlines()[0].strip() if pointer.exists() else str(output_dir)
