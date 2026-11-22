"""Retime an out-of-sync subtitle file against a video's audio using alass."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from jpsubs.clean import Cue, to_srt
from jpsubs.probe import Stream, extract_audio_file, load_sub_file


def find_alass() -> str | None:
    return shutil.which("alass") or shutil.which("alass-cli")


def retime(video: Path, audio: Stream, cues: list[Cue]) -> list[Cue]:
    """Return cues shifted to match the given audio stream. Raises if alass is missing or fails."""
    alass = find_alass()
    if alass is None:
        raise RuntimeError("alass is not installed")
    with tempfile.TemporaryDirectory(prefix="jpsubs-") as tmp:
        ref = Path(tmp) / "ref.wav"
        src = Path(tmp) / "in.srt"
        dst = Path(tmp) / "out.srt"
        # alass picks its own audio stream from a video; hand it the Japanese one explicitly
        extract_audio_file(video, audio, ref)
        src.write_text(to_srt(cues), encoding="utf-8")
        proc = subprocess.run([alass, str(ref), str(src), str(dst)], capture_output=True, text=True)
        if proc.returncode != 0 or not dst.exists():
            raise RuntimeError(f"alass failed: {(proc.stderr or proc.stdout).strip()[-400:]}")
        return load_sub_file(dst)
