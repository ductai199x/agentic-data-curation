# Patches for third_party/ (gitignored) dependencies

Local fixes to upstream repos we clone into `third_party/`. Re-apply after a
fresh clone or upgrade.

## ComfyUI-PyramidFlowWrapper_text-encode-pad.patch

- **Upstream:** https://github.com/kijai/ComfyUI-PyramidFlowWrapper @ `426e365`
- **Target:** `third_party/ComfyUI/custom_nodes/ComfyUI-PyramidFlowWrapper/nodes.py`
- **Problem:** `PyramidFlowTextEncode` encodes the positive and negative prompts
  separately. Long SALMONN captions tokenize to 2 T5 chunks (256 tokens) while
  the short negative prompt stays at 1 chunk (128), so
  `torch.cat([negative, positive])` in `generate_i2v` fails with
  "Expected size 128 but got size 256". Hit 589 clips in the YouTube run.
- **Fix:** zero-pad the shorter embedding and its attention mask to the longer
  length before returning.

Apply:

```bash
git -C third_party/ComfyUI/custom_nodes/ComfyUI-PyramidFlowWrapper \
    apply ../../../../patches/ComfyUI-PyramidFlowWrapper_text-encode-pad.patch
```
