"""Test that multiprocessing workers land on different GPUs."""

import multiprocessing
import os
import time


def worker(gpu_id, worker_id):
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    import torch
    x = torch.zeros(1024, 1024).cuda()  # Allocate ~4MB to show up in nvidia-smi
    print(f"Worker {worker_id}: CUDA_VISIBLE_DEVICES={gpu_id}, "
          f"device_count={torch.cuda.device_count()}, "
          f"device_name={torch.cuda.get_device_name(0)}", flush=True)
    time.sleep(10)  # Hold the allocation


if __name__ == "__main__":
    ctx = multiprocessing.get_context("spawn")
    procs = []
    for i in range(8):
        p = ctx.Process(target=worker, args=(i, i))
        procs.append(p)
        p.start()

    time.sleep(5)
    os.system("nvidia-smi --query-gpu=index,memory.used --format=csv,noheader")

    for p in procs:
        p.join()
