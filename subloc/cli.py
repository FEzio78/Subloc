"""Command line: subloc VIDEO|FOLDER ... [--to ar] [--from ko] [--model ID]"""

import argparse
import sys
from pathlib import Path

from .batch import find_videos, run_batch
from .llm import LMStudio
from .media import probe
from .pipeline import Options, run


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="subloc", description="Local subtitles: transcribe + translate.")
    p.add_argument(
        "videos",
        nargs="*",
        type=Path,
        metavar="VIDEO_OR_FOLDER",
        help="one video, several videos, or a folder (processed as a batch)",
    )
    p.add_argument("--to", default="ar", help="target language code (default: ar)")
    p.add_argument(
        "--from",
        dest="source",
        help="spoken language code, or 'mixed' if it changes during the video (default: auto-detect)",
    )
    p.add_argument("--audio-track", type=int, help="audio track number, 1 = first (default: original language)")
    p.add_argument("--subs", type=int, help="translate built-in subtitle track N (1 = first) instead of listening")
    p.add_argument("--info", action="store_true", help="show the file's audio and subtitle tracks and exit")
    p.add_argument("--model", help="LM Studio model id (default: the loaded model)")
    p.add_argument("--asr-model", default="large-v3", help="Whisper model (large-v3, large-v3-turbo, …)")
    p.add_argument("--url", default="http://localhost:1234", help="LM Studio server")
    p.add_argument(
        "--parallel",
        type=int,
        choices=range(1, 5),
        default=2,
        metavar="1-4",
        help="translation requests sent to LM Studio at once (default: 2)",
    )
    p.add_argument(
        "--no-glossary", action="store_true", help="skip the name pass (names may be spelled inconsistently)"
    )
    p.add_argument("--retranscribe", action="store_true")
    p.add_argument("--retranslate", action="store_true")
    p.add_argument("--models", action="store_true", help="list LM Studio models and exit")
    a = p.parse_args()

    if a.models:
        for m in LMStudio(a.url).list_models():
            print(f"{'*' if m.loaded else ' '} {m.id:50} {'vision' if m.vision else 'text  '}  {m.hint}")
        return
    if not a.videos:
        p.error("give a video or a folder")
    for v in a.videos:
        if not v.exists():
            p.error(f"not found: {v}")

    if a.info:
        info = probe(a.videos[0])
        print(f"{info.duration / 60:.1f} min")
        for t in info.audio:
            print(f"  audio {t.index + 1}: {t.lang or '?'}  {t.title}")
        for t in info.subtitles:
            kind = t.codec if t.is_text else f"{t.codec}, image — not supported"
            print(f"  subs  {t.index + 1}: {t.lang or '?'}  {t.title}  ({kind})")
        return

    opt = Options(
        target=a.to,
        source=a.source,
        asr_model=a.asr_model,
        llm_model=a.model,
        llm_url=a.url,
        retranscribe=a.retranscribe,
        retranslate=a.retranslate,
        audio_track=a.audio_track - 1 if a.audio_track else None,
        subs_track=a.subs - 1 if a.subs else None,
        parallel=a.parallel,
        auto_glossary=not a.no_glossary,
    )
    videos = find_videos(a.videos)
    if not videos:
        p.error("no videos found")
    if len(videos) == 1 and not a.videos[0].is_dir():
        run(videos[0], opt)
        return
    print(f"{len(videos)} videos:")
    for v in videos:
        print(f"  {v.name}")
    items = run_batch(videos, opt)
    sys.exit(1 if any(it.status == "failed" for it in items) else 0)


if __name__ == "__main__":
    main()
