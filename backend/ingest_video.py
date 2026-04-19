"""Video ingestion module.

Responsible for taking the claimant's video walkthrough and extracting:
- Sampled keyframes (at `KEYFRAME_FPS`) saved to disk as images, with
  near-duplicate frames removed via perceptual hashing.
- An audio track transcribed (Groq Whisper) into time-aligned narration
  chunks (windowed by `NARRATION_CHUNK_SEC`, preferring sentence
  boundaries when possible).

Outputs `KeyFrame` and `NarrationChunk` objects (with embeddings) for
downstream stages.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import ffmpeg
import imagehash
from PIL import Image

import config
from embeddings import embed_image, embed_text
from schemas import KeyFrame, NarrationChunk

PHASH_DEDUP_THRESHOLD: int = 5


def _extract_keyframes(video_path: str, frames_dir: Path) -> list[KeyFrame]:
    """Extract 1 fps keyframes, dedup with perceptual hash, embed survivors."""
    try:
        probe = ffmpeg.probe(video_path)
    except ffmpeg.Error as e:
        msg = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
        print(f"[ingest_video] ffprobe failed: {msg}")
        raise

    duration_str = probe.get("format", {}).get("duration")
    if duration_str is None:
        raise RuntimeError(f"Could not determine duration of {video_path}")
    duration = float(duration_str)
    expected = max(1, int(duration))

    pattern = str(frames_dir / "frame_%04d.jpg")
    try:
        (
            ffmpeg.input(video_path)
            .filter("fps", fps=config.KEYFRAME_FPS)
            .output(pattern, start_number=0, **{"qscale:v": 2})
            .overwrite_output()
            .run(quiet=True)
        )
    except ffmpeg.Error as e:
        msg = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
        print(f"[ingest_video] ffmpeg frame extraction failed: {msg}")
        raise

    raw_frames = sorted(frames_dir.glob("frame_*.jpg"))
    if not raw_frames:
        print(f"[ingest_video] WARNING: no frames extracted from {video_path}")
        return []

    kept: list[KeyFrame] = []
    last_phash: imagehash.ImageHash | None = None

    for frame_path in raw_frames:
        try:
            frame_idx = int(frame_path.stem.split("_")[1])
        except (IndexError, ValueError):
            print(f"[ingest_video] skipping unrecognized frame name: {frame_path.name}")
            continue

        if frame_idx >= expected + 2:
            frame_path.unlink(missing_ok=True)
            continue

        with Image.open(frame_path) as img:
            phash = imagehash.phash(img)

        if last_phash is not None and (phash - last_phash) < PHASH_DEDUP_THRESHOLD:
            frame_path.unlink(missing_ok=True)
            continue

        last_phash = phash
        timestamp = frame_idx * 1.0
        embedding = embed_image(str(frame_path))
        kept.append(
            KeyFrame(
                frame_id=f"frame_{frame_idx:04d}",
                timestamp_sec=timestamp,
                image_path=str(frame_path),
                embedding=embedding,
            )
        )

    return kept


def _extract_audio_for_transcription(video_path: str) -> str:
    """Extract a small mono 16kHz mp3 so we stay under Groq's 25MB upload cap."""
    fd, audio_path = tempfile.mkstemp(suffix=".mp3", prefix="claim_audio_")
    os.close(fd)
    try:
        (
            ffmpeg.input(video_path)
            .output(
                audio_path,
                vn=None,
                ac=1,
                ar=16000,
                **{"b:a": "64k"},
                format="mp3",
            )
            .overwrite_output()
            .run(quiet=True)
        )
    except ffmpeg.Error as e:
        msg = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
        print(f"[ingest_video] audio extraction failed: {msg}")
        try:
            os.remove(audio_path)
        except OSError:
            pass
        raise
    return audio_path


def _transcribe(video_path: str) -> list[dict[str, Any]]:
    """Send the video's audio to Groq Whisper and return word-level timestamps."""
    if not config.GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set; cannot transcribe audio. "
            "Add it to backend/.env."
        )

    from groq import Groq

    client = Groq(api_key=config.GROQ_API_KEY)

    audio_path = _extract_audio_for_transcription(video_path)
    audio_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    print(f"[ingest_video] extracted audio: {audio_path} ({audio_size_mb:.2f} MB)")

    try:
        with open(audio_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f.read()),
                model="whisper-large-v3",
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )
    except Exception as e:
        print(f"[ingest_video] Groq transcription failed: {e}")
        raise
    finally:
        try:
            os.remove(audio_path)
        except OSError:
            pass

    raw_words = getattr(transcription, "words", None)
    if raw_words is None and isinstance(transcription, dict):
        raw_words = transcription.get("words")
    if not raw_words:
        return []

    words: list[dict[str, Any]] = []
    for w in raw_words:
        if isinstance(w, dict):
            text = w.get("word", "")
            start = float(w.get("start", 0.0))
            end = float(w.get("end", start))
        else:
            text = getattr(w, "word", "")
            start = float(getattr(w, "start", 0.0))
            end = float(getattr(w, "end", start))
        text = text.strip()
        if not text:
            continue
        words.append({"word": text, "start": start, "end": end})
    return words


def _chunk_narration(
    words: list[dict[str, Any]], claim_id: str
) -> list[NarrationChunk]:
    """Group word-level timestamps into ~NARRATION_CHUNK_SEC chunks.

    Greedy fill up to the time window; finalize early on a sentence
    terminator (. ! ?) once we've accumulated at least half the window,
    so chunks land on natural sentence boundaries when available.
    """
    if not words:
        return []

    window = float(config.NARRATION_CHUNK_SEC)
    min_close_on_sentence = window / 2.0
    sentence_enders = (".", "!", "?")

    chunks: list[NarrationChunk] = []
    current: list[dict[str, Any]] = []
    chunk_start: float = words[0]["start"]

    def flush() -> None:
        nonlocal current, chunk_start
        if not current:
            return
        text = " ".join(w["word"] for w in current).strip()
        chunk = NarrationChunk(
            chunk_id=f"{claim_id}_chunk_{len(chunks):04d}",
            start_sec=current[0]["start"],
            end_sec=current[-1]["end"],
            text=text,
            embedding=embed_text(text) if text else None,
        )
        chunks.append(chunk)
        current = []

    for w in words:
        if not current:
            chunk_start = w["start"]
            current.append(w)
            continue

        prospective_end = w["end"]
        if (prospective_end - chunk_start) > window:
            flush()
            chunk_start = w["start"]
            current.append(w)
            continue

        current.append(w)
        elapsed = w["end"] - chunk_start
        if elapsed >= min_close_on_sentence and w["word"].endswith(sentence_enders):
            flush()

    flush()
    return chunks


def _cache_path(claim_id: str) -> Path:
    return Path(config.OUTPUT_DIR) / claim_id / "ingest_cache.json"


def _load_cache(
    claim_id: str,
) -> tuple[list[KeyFrame], list[NarrationChunk]] | None:
    p = _cache_path(claim_id)
    if not p.is_file():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        frames = [KeyFrame(**fr) for fr in data["frames"]]
        chunks = [NarrationChunk(**c) for c in data["narration"]]
        return frames, chunks
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"[ingest_video] cache read failed ({e}); re-ingesting")
        return None


def _save_cache(
    claim_id: str, frames: list[KeyFrame], chunks: list[NarrationChunk]
) -> None:
    p = _cache_path(claim_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(
            {
                "frames": [asdict(fr) for fr in frames],
                "narration": [asdict(c) for c in chunks],
            },
            f,
        )


def ingest_video(
    video_path: str,
    claim_id: str,
    use_cache: bool = True,
) -> tuple[list[KeyFrame], list[NarrationChunk]]:
    """Run the full video ingestion pipeline for a single claim.

    Args:
        video_path: Path to the source walkthrough video.
        claim_id: Unique identifier; used for output directory layout
            and to namespace narration chunk ids.
        use_cache: If True (default), reuse a previous ingestion's
            output from `outputs/{claim_id}/ingest_cache.json` when
            present, skipping ffmpeg/Whisper/CLIP work entirely. Pass
            False to force a fresh ingest (e.g. when the source video
            has changed).

    Returns:
        (keyframes, narration_chunks) — both already embedded.
    """
    if use_cache:
        cached = _load_cache(claim_id)
        if cached is not None:
            frames, chunks = cached
            print(
                f"[ingest_video] cache hit for claim={claim_id!r}: "
                f"{len(frames)} frames + {len(chunks)} chunks"
            )
            return frames, chunks

    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    claim_dir = Path(config.OUTPUT_DIR) / claim_id
    frames_dir = claim_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    keyframes = _extract_keyframes(video_path, frames_dir)
    words = _transcribe(video_path)
    chunks = _chunk_narration(words, claim_id)

    _save_cache(claim_id, keyframes, chunks)
    return keyframes, chunks


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ingest_video.py <video_path>")
        sys.exit(1)

    video_arg = sys.argv[1]
    claim_id = "test"

    keyframes, narration_chunks = ingest_video(video_arg, claim_id)

    print(f"Frames kept: {len(keyframes)}")
    print(f"Narration chunks: {len(narration_chunks)}")
    if narration_chunks:
        print(f"First chunk: {narration_chunks[0].text!r}")
        print(f"Last chunk:  {narration_chunks[-1].text!r}")
    else:
        print("No narration chunks produced.")

    summary = {
        "video_path": video_arg,
        "claim_id": claim_id,
        "frames_kept": len(keyframes),
        "narration_chunks": len(narration_chunks),
        "frames": [
            {
                "frame_id": kf.frame_id,
                "timestamp_sec": kf.timestamp_sec,
                "image_path": kf.image_path,
                "embedding_dim": len(kf.embedding) if kf.embedding else 0,
            }
            for kf in keyframes
        ],
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "start_sec": c.start_sec,
                "end_sec": c.end_sec,
                "text": c.text,
                "embedding_dim": len(c.embedding) if c.embedding else 0,
            }
            for c in narration_chunks
        ],
    }

    summary_path = Path(config.OUTPUT_DIR) / claim_id / "ingest_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote {summary_path}")
