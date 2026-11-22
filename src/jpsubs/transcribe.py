"""Speech recognition with faster-whisper on the GPU."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Callable

import numpy as np

from jpsubs.clean import Cue, Word, split_words
from jpsubs.probe import SAMPLE_RATE

DEFAULT_MODEL = "large-v3-turbo"
_REEXEC_FLAG = "JPSUBS_CUDA_LIBS_SET"


def ensure_cuda_libs() -> None:
    """Put the pip-installed CUDA libraries on the loader path.

    The dynamic loader only reads LD_LIBRARY_PATH at process start, so this
    re-executes the program once with the variable set.
    """
    if os.environ.get(_REEXEC_FLAG) or sys.platform != "linux":
        return
    dirs = []
    for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"):
        try:
            spec = importlib.util.find_spec(pkg)
        except ModuleNotFoundError:
            spec = None
        for loc in (spec.submodule_search_locations if spec else None) or []:
            lib = Path(loc) / "lib"
            if lib.is_dir():
                dirs.append(str(lib))
    if not dirs:
        return
    env = dict(os.environ)
    env[_REEXEC_FLAG] = "1"
    env["LD_LIBRARY_PATH"] = os.pathsep.join(dirs + [p for p in [env.get("LD_LIBRARY_PATH")] if p])
    os.execve(sys.executable, [sys.executable, "-m", "jpsubs", *sys.argv[1:]], env)


class Transcriber:
    def __init__(self, model: str = DEFAULT_MODEL, device: str = "cuda"):
        from faster_whisper import WhisperModel

        compute = "float16" if device == "cuda" else "int8"
        self.model = WhisperModel(model, device=device, compute_type=compute)

    def transcribe(self, audio: np.ndarray, progress: Callable[[float], None] | None = None) -> list[Cue]:
        duration = len(audio) / SAMPLE_RATE
        segments, _info = self.model.transcribe(
            audio,
            language="ja",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            # each window is decoded on its own: a mistake cannot snowball into a repeat loop
            condition_on_previous_text=False,
            word_timestamps=True,
            hallucination_silence_threshold=2.0,
        )
        cues: list[Cue] = []
        for seg in segments:
            words = [Word(w.start, w.end, w.word) for w in (seg.words or [])]
            if words:
                cues.extend(split_words(words))
            elif seg.text.strip():
                cues.append(Cue(seg.start, seg.end, seg.text.strip()))
            if progress and duration:
                progress(min(1.0, seg.end / duration))
        return cues
