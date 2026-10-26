# Generator releases (input to `adapt trigger`)

One row per release. Columns: Date (release, UTC day or ISO time) | Name | Maker | Modality (image/video) |
Weights (open/closed) | Link | Detected (when the generator watch first reported it, ISO time).
Agents append rows here from the generator watch posts; a new row is what starts an adaptation run.

| Date | Name | Maker | Modality | Weights | Link | Detected |
|---|---|---|---|---|---|---|
| 2026-08-11 | LTX-2.5 | Lightricks | video | open | https://comfyui-wiki.com/ja/news/2026-08-11-ltx-2-5-open-weights-release | 2026-10-26T00:19:41Z |
| 2026-10-09 | Qwen-Image-2.1-Turbo | Alibaba Qwen | image | open | https://www.orcarouter.ai/blog/qwen-image-2-1-turbo-release | 2026-10-26T01:15:00Z |
| 2026-10-20 | VideoGen Model 1 | VideoGen | video | closed | https://www.globenewswire.com/news-release/2026/10/20/3384785/0/en/videogen-unveils-model-1-its-first-ai-video-generation-model-and-1-million-in-free-ai-credits.html | 2026-10-26T00:19:41Z |
| 2026-10-22 | Canva Craft | Canva | image | closed | https://techcrunch.com/2026/10/22/canva-releases-its-first-image-generation-model/ | 2026-10-26T00:19:41Z |
| 2026-10-23 | Seedance 2.5 4K | ByteDance | video | closed | https://technode.com/2026/10/23/bytedance-launches-seedance-2-5-4k-video-model-for-film-production/ | 2026-10-26T00:19:41Z |

The watch also logged Kling 3.0, MiniMax H3 and Gemini Omni as its baseline; add them with their release dates when an
adaptation run for them is wanted.
