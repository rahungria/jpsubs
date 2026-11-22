"""ffprobe/ffmpeg wrappers: stream discovery, audio decoding, subtitle loading."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pysubs2

from jpsubs.clean import Cue

JA_LANGS = {"ja", "jpn", "jp", "japanese"}
EN_LANGS = {"en", "eng", "english"}
TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}
SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt"}
VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".webm", ".avi", ".mov"}
SAMPLE_RATE = 16000
# tracks that only carry on-screen text or lyrics, not dialogue
_NOT_DIALOGUE = ("sign", "song", "karaoke", "forced", "commentary")
# subtitle styles that are not spoken dialogue: songs, on-screen text, previews, notes
_NOT_SPEECH_STYLE = re.compile(
    r"(?<![a-z])(op|ed|ts|pv|insert|eyecatch)(?![a-z])"
    r"|sign|song|title|kara|lyric|roma[nj]|note|credit|caption|preview",
    re.IGNORECASE,
)
# override tags used for placed text and karaoke rather than dialogue
_NOT_SPEECH_TAGS = re.compile(r"\\(pos|move|org|clip|k[fo]?\d)")
MIN_WINDOW = 0.3  # seconds; shorter events are flashes of on-screen text


@dataclass
class Stream:
    index: int
    kind: str
    codec: str
    lang: str = ""
    title: str = ""
    default: bool = False
    forced: bool = False


def probe(path: Path) -> list[Stream]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return parse_streams(json.loads(proc.stdout))


def parse_streams(data: dict) -> list[Stream]:
    streams = []
    for s in data.get("streams", []):
        tags = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
        disp = s.get("disposition") or {}
        streams.append(
            Stream(
                index=s["index"],
                kind=s.get("codec_type", ""),
                codec=s.get("codec_name", ""),
                lang=str(tags.get("language", "")).lower(),
                title=str(tags.get("title", "")),
                default=bool(disp.get("default")),
                forced=bool(disp.get("forced")),
            )
        )
    return streams


def pick_audio(streams: list[Stream]) -> Stream | None:
    """Japanese audio track if tagged, otherwise the default, otherwise the first."""
    audio = [s for s in streams if s.kind == "audio"]
    if not audio:
        return None
    ja = [s for s in audio if s.lang in JA_LANGS or "japanese" in s.title.lower()]
    not_commentary = [s for s in ja if "commentary" not in s.title.lower()]
    for group in (not_commentary, ja, [s for s in audio if s.default], audio):
        if group:
            return group[0]
    return None


def pick_subs(streams: list[Stream], langs: set[str]) -> list[Stream]:
    """Text subtitle tracks tagged with one of the languages, dialogue tracks first."""
    subs = [s for s in streams if s.kind == "subtitle" and s.codec in TEXT_SUB_CODECS and s.lang in langs]
    return sorted(subs, key=lambda s: (_is_not_dialogue(s), s.index))


def pick_ja_subs(streams: list[Stream]) -> list[Stream]:
    return pick_subs(streams, JA_LANGS)


def dialogue_track_order(streams: list[Stream]) -> list[Stream]:
    """Text subtitle tracks ordered by how likely they are to time the dialogue.

    Any language will do, since only the timing is used; English comes first
    because it is the track most releases carry in full.
    """
    subs = [s for s in streams if s.kind == "subtitle" and s.codec in TEXT_SUB_CODECS]
    return sorted(subs, key=lambda s: (_is_not_dialogue(s), s.lang not in EN_LANGS, s.index))


def _is_not_dialogue(s: Stream) -> bool:
    return s.forced or any(word in s.title.lower() for word in _NOT_DIALOGUE)


def find_sidecar_subs(video: Path, output: Path) -> list[Path]:
    """Subtitle files next to the video sharing its name, excluding our own output."""
    found = []
    for p in sorted(video.parent.iterdir()):
        if p == output or p.suffix.lower() not in SUB_EXTS or not p.is_file():
            continue
        if p.stem == video.stem or p.name.startswith(video.stem + "."):
            found.append(p)
    return found


def decode_audio(path: Path, stream: Stream) -> np.ndarray:
    """Decode one audio stream to 16 kHz mono float32, the format Whisper wants."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-map", f"0:{stream.index}",
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32)


def extract_audio_file(path: Path, stream: Stream, out: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(path), "-map", f"0:{stream.index}",
         "-ac", "1", "-ar", str(SAMPLE_RATE), str(out)],
        check=True,
    )


def load_embedded_subs(path: Path, stream: Stream) -> list[Cue]:
    return _to_cues(_load_embedded(path, stream))


def load_sub_file(path: Path) -> list[Cue]:
    """Load any text subtitle file as plain-text cues (styling and drawings removed)."""
    return _to_cues(_load_any_encoding(path))


def load_dialogue_windows(path: Path, stream: Stream) -> list[tuple[float, float]]:
    return dialogue_windows(_load_embedded(path, stream))


def dialogue_windows(subs: pysubs2.SSAFile) -> list[tuple[float, float]]:
    """When spoken dialogue happens according to a subtitle track: (start, end) in seconds.

    Songs, signs, previews and other placed text are left out.
    """
    windows = []
    for ev in subs.events:
        if ev.is_comment or ev.is_drawing or not ev.plaintext.strip():
            continue
        if _NOT_SPEECH_STYLE.search(ev.style) or _NOT_SPEECH_TAGS.search(ev.text):
            continue
        start, end = ev.start / 1000, ev.end / 1000
        if end - start >= MIN_WINDOW:
            windows.append((start, end))
    return sorted(windows)


def _load_embedded(path: Path, stream: Stream) -> pysubs2.SSAFile:
    with tempfile.TemporaryDirectory(prefix="jpsubs-") as tmp:
        out = Path(tmp) / "track.ass"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(path), "-map", f"0:{stream.index}", str(out)],
            check=True,
        )
        return _load_any_encoding(out)


def _to_cues(subs: pysubs2.SSAFile) -> list[Cue]:
    cues = []
    for ev in subs.events:
        if ev.is_comment or ev.is_drawing:
            continue
        text = ev.plaintext.strip()
        if text:
            cues.append(Cue(ev.start / 1000, ev.end / 1000, text))
    return cues


def _load_any_encoding(path: Path) -> pysubs2.SSAFile:
    last: Exception | None = None
    for enc in ("utf-8-sig", "utf-16", "shift_jis", "euc_jp"):
        try:
            return pysubs2.load(str(path), encoding=enc)
        except (UnicodeError, pysubs2.exceptions.Pysubs2Error) as exc:
            last = exc
    raise ValueError(f"cannot read subtitle file {path}: {last}")
