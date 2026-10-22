"""Read-only media inspection using the first audio stream."""

import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path


class MediaError(ValueError):
    pass


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def probe(path: Path) -> dict:
    if not shutil.which("ffprobe"):
        raise MediaError("找不到 ffprobe；请安装 FFmpeg 并加入 PATH。")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_streams", "-show_format", "-of", "json", str(path.resolve())],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if result.returncode:
        raise MediaError(f"无法读取音频：{result.stderr.strip()[:1000]}")
    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise MediaError("文件中没有音轨。")
    stream = data["streams"][0]
    duration = stream.get("duration") or data.get("format", {}).get("duration")
    try:
        duration = float(duration)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError()
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
        if sample_rate <= 0 or channels <= 0:
            raise ValueError()
    except (TypeError, ValueError, KeyError) as exc:
        raise MediaError("音频时长、采样率或声道无效。") from exc
    return {"duration": duration, "sample_rate": sample_rate, "channels": channels,
            "codec": stream.get("codec_name", "unknown"), "audio_stream": stream["index"]}


def extract_audio(source: Path, target: Path) -> None:
    """Normalize a disposable inference input, never the archived original."""
    if not shutil.which("ffmpeg"):
        raise MediaError("找不到 ffmpeg；请安装 FFmpeg 并加入 PATH。")
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(source),
         "-map", "0:a:0", "-vn", "-c:a", "pcm_f32le", str(target)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
    )
    if result.returncode:
        raise MediaError(result.stderr.strip()[:1000])
