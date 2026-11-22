"""Command line: write a <video>.ja.srt next to each video."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from jpsubs import probe
from jpsubs.clean import Cue, clean_cues, fix_timing, looks_japanese, to_srt
from jpsubs.gapfill import second_look
from jpsubs.retime import find_alass, retime
from jpsubs.transcribe import DEFAULT_MODEL, Transcriber, ensure_cuda_libs

MIN_CUES = 5  # fewer than this and a track is signs/credits, not dialogue
MIN_DIALOGUE_WINDOWS = 20  # a track with fewer timed lines cannot map an episode's dialogue
MAX_TRACKS_TRIED = 3


@dataclass
class Result:
    video: Path
    status: str  # written | skipped | failed | planned
    detail: str


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    if not args.dry_run:
        ensure_cuda_libs()

    videos = _collect(args.paths)
    if not videos:
        print("no video files found", file=sys.stderr)
        return 1
    if args.subs and len(videos) != 1:
        print("--subs needs exactly one video", file=sys.stderr)
        return 2

    runner = _Runner(args)
    results = []
    for i, video in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] {video.name}", flush=True)
        try:
            res = runner.process(video)
        except KeyboardInterrupt:
            print("\ninterrupted", file=sys.stderr)
            break
        except (subprocess.CalledProcessError, RuntimeError, ValueError, OSError) as exc:
            detail = _stderr(exc) or str(exc)
            res = Result(video, "failed", detail)
        print(f"    {res.status}: {res.detail}", flush=True)
        results.append(res)

    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    print("done: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
    return 1 if counts.get("failed") else 0


def _parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="jpsubs",
        description="Write Japanese subtitles (<video>.ja.srt) next to each video: "
        "embedded Japanese track, else a subtitle file beside the video (retimed), else Whisper.",
    )
    p.add_argument("paths", nargs="+", type=Path, help="video files or folders (searched recursively)")
    p.add_argument("--subs", type=Path, help="subtitle file to use for a single video (retimed to its audio)")
    p.add_argument("--whisper-only", action="store_true", help="ignore existing subtitles, always transcribe")
    p.add_argument("--no-retime", action="store_true", help="use external subtitle files without retiming")
    p.add_argument(
        "--no-second-look",
        action="store_true",
        help="skip re-transcribing dialogue that Whisper's first pass left without a line",
    )
    p.add_argument("--force", action="store_true", help="redo videos that already have a .ja.srt (old file kept as .bak)")
    p.add_argument("--dry-run", action="store_true", help="show which source each video would use, write nothing")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Whisper model name or path (default {DEFAULT_MODEL})")
    p.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    return p.parse_args(argv)


def _collect(paths: list[Path]) -> list[Path]:
    videos: list[Path] = []
    for path in paths:
        if path.is_dir():
            videos += sorted(
                f for f in path.rglob("*") if f.suffix.lower() in probe.VIDEO_EXTS and f.is_file()
            )
        elif path.is_file():
            videos.append(path)
        else:
            print(f"not found: {path}", file=sys.stderr)
    return videos


class _Runner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self._transcriber: Transcriber | None = None

    def process(self, video: Path) -> Result:
        args = self.args
        output = video.parent / f"{video.stem}.ja.srt"
        if output.exists() and not args.force:
            return Result(video, "skipped", f"{output.name} already exists")

        streams = probe.probe(video)
        audio = probe.pick_audio(streams)

        cues: list[Cue] | None = None
        source = ""
        if not args.whisper_only:
            cues, source = self._from_existing(video, output, streams, audio)

        if cues is None:
            if audio is None:
                return Result(video, "failed", "no audio track")
            source = f"whisper {args.model} (audio track #{audio.index} {audio.lang or 'untagged'})"
            if args.dry_run:
                return Result(video, "planned", source)
            cues, recovered = self._whisper(video, audio, streams)
            if recovered:
                source += f", {recovered} recovered by second look"

        if args.dry_run:
            return Result(video, "planned", source)
        if not cues:
            return Result(video, "failed", f"{source}: no subtitle lines produced")

        if output.exists():
            backup = output.with_name(output.name + ".bak")
            if not backup.exists():
                output.rename(backup)
        output.write_text(to_srt(cues), encoding="utf-8")
        return Result(video, "written", f"{len(cues)} lines from {source}")

    def _from_existing(self, video, output, streams, audio) -> tuple[list[Cue] | None, str]:
        args = self.args
        if not args.subs:
            for stream in probe.pick_ja_subs(streams):
                cues = clean_cues(probe.load_embedded_subs(video, stream))
                if len(cues) >= MIN_CUES and looks_japanese(cues):
                    return cues, f"embedded track #{stream.index} ({stream.title or stream.codec})"

        candidates = [args.subs] if args.subs else probe.find_sidecar_subs(video, output)
        for path in candidates:
            cues = clean_cues(probe.load_sub_file(path))
            if len(cues) < MIN_CUES or not looks_japanese(cues):
                if args.subs:
                    raise ValueError(f"{path.name} does not look like Japanese subtitles")
                continue
            note = "not retimed"
            if not args.no_retime and audio is not None:
                if find_alass() is None:
                    note = "not retimed: alass not installed"
                elif args.dry_run:
                    note = "would retime with alass"
                else:
                    cues = clean_cues(retime(video, audio, cues))
                    note = "retimed with alass"
            return cues, f"{path.name} ({note})"
        return None, ""

    def _whisper(self, video: Path, audio: probe.Stream, streams: list[probe.Stream]) -> tuple[list[Cue], int]:
        """Transcribe one video. Returns the cues and how many the second look added."""
        if self._transcriber is None:
            print(f"    loading model {self.args.model} ...", flush=True)
            self._transcriber = Transcriber(self.args.model, self.args.device)
        samples = probe.decode_audio(video, audio)
        started = time.monotonic()
        tty = sys.stderr.isatty()

        def progress(frac: float) -> None:
            if tty:
                print(f"\r    transcribing {frac:4.0%}", end="", file=sys.stderr, flush=True)

        cues = clean_cues(self._transcriber.transcribe(samples, progress), drop_hallucinations=True)
        if tty:
            print("\r" + " " * 30 + "\r", end="", file=sys.stderr)

        recovered: list[Cue] = []
        if not self.args.no_second_look:
            windows = self._dialogue_windows(video, streams)
            recovered = clean_cues(
                second_look(self._transcriber, samples, windows, cues), drop_hallucinations=True
            )
            cues = clean_cues(cues + recovered, drop_hallucinations=True)
        print(f"    transcribed in {time.monotonic() - started:.0f}s", flush=True)
        return fix_timing(cues), len(recovered)

    def _dialogue_windows(self, video: Path, streams: list[probe.Stream]) -> list[tuple[float, float]]:
        """When dialogue happens, from the first subtitle track that times a whole episode."""
        for stream in probe.dialogue_track_order(streams)[:MAX_TRACKS_TRIED]:
            try:
                windows = probe.load_dialogue_windows(video, stream)
            except (subprocess.CalledProcessError, ValueError):
                continue
            if len(windows) >= MIN_DIALOGUE_WINDOWS:
                return windows
        return []


def _stderr(exc: Exception) -> str:
    err = getattr(exc, "stderr", None)
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    return (err or "").strip()[-400:]
