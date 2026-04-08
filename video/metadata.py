"""Video metadata extraction via ffprobe.

Extract duration, resolution, fps, codec, bitrate from video files.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VideoMeta:
    """Metadata for a single video file."""
    path: Path
    duration: float          # seconds
    width: int
    height: int
    fps: float
    codec: str               # e.g. "h264", "vp9", "av1"
    bitrate: int             # bps, 0 if unknown
    file_size: int           # bytes
    pixel_format: str        # e.g. "yuv420p"
    has_audio: bool

    @property
    def resolution_label(self) -> str:
        """Human-readable resolution label."""
        h = self.height
        if h >= 2160:
            return "2160p"
        if h >= 1440:
            return "1440p"
        if h >= 1080:
            return "1080p"
        if h >= 720:
            return "720p"
        if h >= 480:
            return "480p"
        return f"{h}p"

    @property
    def pixels(self) -> int:
        return self.width * self.height


def probe(path: str | Path) -> VideoMeta:
    """Extract metadata from a video file using ffprobe.

    Raises FileNotFoundError if file doesn't exist.
    Raises RuntimeError if ffprobe fails or no video stream found.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")

    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {result.stderr[:200]}")

    data = json.loads(result.stdout)

    # Find video stream
    video_stream = None
    has_audio = False
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
        elif stream.get("codec_type") == "audio":
            has_audio = True

    if not video_stream:
        raise RuntimeError(f"No video stream found in {path}")

    # Parse FPS from r_frame_rate (e.g. "30/1", "30000/1001")
    fps_str = video_stream.get("r_frame_rate", "0/1")
    try:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0

    # Duration: prefer stream duration, fall back to format duration
    duration = float(video_stream.get("duration", 0))
    if duration == 0:
        duration = float(data.get("format", {}).get("duration", 0))

    # Bitrate: prefer stream, fall back to format
    bitrate = int(video_stream.get("bit_rate", 0))
    if bitrate == 0:
        bitrate = int(data.get("format", {}).get("bit_rate", 0))

    return VideoMeta(
        path=path,
        duration=duration,
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        fps=round(fps, 3),
        codec=video_stream.get("codec_name", "unknown"),
        bitrate=bitrate,
        file_size=path.stat().st_size,
        pixel_format=video_stream.get("pix_fmt", "unknown"),
        has_audio=has_audio,
    )
