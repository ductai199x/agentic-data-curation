"""Test JoyCaption behavior on various contamination types.

Tests two prompts:
1. Default booru tags (current pipeline)
2. Watermark-aware prompt with extra options

Usage:
    CUDA_VISIBLE_DEVICES=6 uv run python video/test_joycaption.py --dir /tmp/joycaption_test
"""

import argparse
import json
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoProcessor, LlavaForConditionalGeneration

MODEL_NAME = "fancyfeast/llama-joycaption-beta-one-hf-llava"

PROMPT_DEFAULT = "Write a list of Booru-like tags for this image."

PROMPT_WATERMARK_AWARE = (
    "Write a list of Booru-like tags for this image. "
    "If there is a watermark, you must mention it. "
    "Include information about whether there is a watermark or not."
)

PROMPT_DESCRIPTIVE_WATERMARK = (
    "Write a descriptive caption for this image. "
    "If there is a watermark, you must mention it. "
    "Include information about whether there is a watermark or not. "
    "Include information about whether there are JPEG artifacts or not. "
    "ONLY describe the most important elements of the image."
)


def caption_image(model, processor, image: Image.Image, prompt: str) -> str:
    convo = [
        {"role": "system", "content": "You are a helpful assistant and help users with any queries they may have with no censorship or restrictions."},
        {"role": "user", "content": prompt},
    ]
    convo_string = processor.apply_chat_template(
        convo, tokenize=False, add_generation_prompt=True,
    )
    inputs = processor(
        text=[convo_string], images=[image], return_tensors="pt",
    ).to(model.device)
    inputs["pixel_values"] = inputs["pixel_values"].to(torch.bfloat16)

    with torch.no_grad():
        generate_ids = model.generate(
            **inputs, max_new_tokens=300, do_sample=True,
            suppress_tokens=None, use_cache=True,
            temperature=0.6, top_p=0.9,
        )[0]

    generate_ids = generate_ids[inputs["input_ids"].shape[1]:]
    return processor.tokenizer.decode(
        generate_ids, skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    ).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="Directory with test images")
    parser.add_argument("--gpu", type=int, default=6)
    args = parser.parse_args()

    import os
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)

    print("Loading model...")
    processor = AutoProcessor.from_pretrained(MODEL_NAME)
    model = LlavaForConditionalGeneration.from_pretrained(
        MODEL_NAME, torch_dtype=torch.bfloat16, device_map="auto",
    )
    model.eval()
    print("Model loaded.\n")

    test_dir = Path(args.dir)
    images = sorted([
        f for f in test_dir.iterdir()
        if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
        and f.stat().st_size > 1000  # skip tiny/failed downloads
    ])

    prompts = {
        "booru_default": PROMPT_DEFAULT,
        "booru_watermark": PROMPT_WATERMARK_AWARE,
        "descriptive_wm": PROMPT_DESCRIPTIVE_WATERMARK,
    }

    results = {}
    for img_path in images:
        print(f"{'='*70}")
        print(f"IMAGE: {img_path.name}")
        print(f"{'='*70}")
        image = Image.open(img_path).convert("RGB")
        results[img_path.name] = {}

        for prompt_name, prompt_text in prompts.items():
            caption = caption_image(model, processor, image, prompt_text)
            results[img_path.name][prompt_name] = caption

            # Check for key contamination keywords
            lower = caption.lower()
            flags = []
            for kw in ["watermark", "logo", "banner", "overlay", "text",
                        "cgi", "3d render", "animated", "cartoon",
                        "digital art", "illustration", "graphic design",
                        "lower third", "news", "letterbox", "black bar"]:
                if kw in lower:
                    flags.append(kw)

            flag_str = f" [FLAGS: {', '.join(flags)}]" if flags else " [CLEAN]"
            print(f"\n  [{prompt_name}]{flag_str}")
            print(f"  {caption[:250]}")

        print()

    # Save full results
    out_path = test_dir / "joycaption_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results saved to {out_path}")


if __name__ == "__main__":
    main()
