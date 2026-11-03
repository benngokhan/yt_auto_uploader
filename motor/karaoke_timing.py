"""Audio-grounded Turkish word timings for Bilgi Dozu subtitles.

A word is NEVER timed by character-count or by a fixed fraction of a scene.
For each narration clip, Whisper is given the actual audio and the known spoken
text; cross-attention alignment yields per-word boundaries.  A separate ASR
pass checks that the speech and caption roughly agree.  Short silence onsets
are refined from the actual waveform.  Alignment is approximate, not a claim
of phoneme-perfect timestamps; listening/visual QC remains important.

For unattended production use, install the optional requirements listed in
requirements-karaoke.txt, or attach precomputed alignment dictionaries generated
by this module to each scene as ``scene['karaoke']``.  If neither is available,
the renderer fails instead of silently creating misleading static highlights.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


class AlignmentError(ValueError):
    """The voice and subtitles could not safely be aligned."""


def digest_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def transcript_of_subtitles(subs: Iterable[Any]) -> str:
    """Flatten the existing (text, old_highlights) subtitle chunk structure."""
    out: list[str] = []
    for group in subs:
        text = group if isinstance(group, str) else group[0]
        if not isinstance(text, str) or not text.split():
            raise AlignmentError("Altyazı grubu boş veya metin değil")
        out.extend(text.split())
    if not out:
        raise AlignmentError("Seslendirme için altyazı metni boş")
    return " ".join(out)


def _canonical(text: str) -> str:
    # Apostrophes and punctuation do not affect spoken-word matching.  Casefold
    # of Turkish İ can introduce a combining dot, which should not split words.
    s = unicodedata.normalize("NFKD", text.casefold().replace("ı", "i"))
    return "".join(c for c in s if c.isalnum() and unicodedata.category(c) != "Mn")


def merge_alignment_words(raw: list[dict[str, Any]], expected: list[str]) -> list[dict[str, Any]]:
    """Merge tokenizer pieces into display words, without inventing timings.

    Whisper can split a Turkish apostrophe suffix (Üniversitesi + 'nde) or
    spell one written word using several token groups.  Only concatenations
    that exactly match the supplied displayed word after punctuation folding
    are accepted; an unmatched word raises an error instead of being guessed.
    """
    raw = [r for r in raw if _canonical(str(r.get("word", "")))]
    result: list[dict[str, Any]] = []
    pos = 0
    for shown in expected:
        target = _canonical(shown)
        if not target:
            raise AlignmentError(f"Zamanlanacak sözcük geçersiz: {shown!r}")
        acc = ""
        pieces = []
        while pos < len(raw) and len(acc) < len(target):
            piece = raw[pos]
            acc += _canonical(str(piece["word"]))
            pieces.append(piece)
            pos += 1
            if not target.startswith(acc):
                raise AlignmentError(f"Sözcük eşleşmiyor: {shown!r} / {acc!r}")
        if acc != target or not pieces:
            raise AlignmentError(f"Sözcük zamanlaması eksik: {shown!r}")
        result.append({
            "word": shown,
            "start": round(float(pieces[0]["start"]), 4),
            "end": round(float(pieces[-1]["end"]), 4),
            "probability": round(min(float(x.get("probability", 1.0)) for x in pieces), 4),
        })
    if pos != len(raw):
        raise AlignmentError("Seste hizalanan fazla sözcük/parça var")
    return result


def refine_pauses(words: list[dict[str, Any]], audio: Any, sr: int) -> list[dict[str, Any]]:
    """Adjust obvious silent phrase onsets using the actual narration waveform.

    Only silence runs >=60ms near a word boundary can move that boundary;
    no part of a clip is divided according to character/word count.  This is a
    conservative onset correction, not a replacement for human listening.
    """
    import numpy as np

    y = np.asarray(audio, dtype=np.float32).reshape(-1)
    win = max(1, int(round(sr * 0.01)))
    count = len(y) // win
    if count < 8:
        return [dict(w) for w in words]
    rms = np.sqrt(np.mean(y[:count * win].reshape(count, win) ** 2, axis=1) + 1e-12)
    threshold = max(0.0025, float(np.percentile(rms, 90)) * 0.025)
    quiet = rms < threshold
    runs: list[tuple[float, float]] = []
    i = 0
    while i < count:
        if not quiet[i]:
            i += 1
            continue
        j = i + 1
        while j < count and quiet[j]:
            j += 1
        if j - i >= 6:
            runs.append((i * 0.01, j * 0.01))
        i = j

    refined = [dict(w) for w in words]
    for n, w in enumerate(refined):
        start = float(w["start"])
        end = float(w["end"])
        candidates = [
            (a, b) for a, b in runs
            if a <= start + 0.02 and b > start + 0.04
            and b <= start + 0.25 and b < end - 0.06
            and b - start > 0
        ]
        if not candidates:
            continue
        a, b = min(candidates, key=lambda ab: abs(ab[1] - start))
        new_start = min(end - 0.06, b - 0.02)
        if new_start <= start + 0.02:
            continue
        w["start"] = round(new_start, 4)
        w["pause_refined_from"] = round(start, 4)
        if n:
            prev = refined[n - 1]
            # When the model joined two words across a short silence, keep the
            # previous highlight through its actual audio, but not the gap.
            if abs(float(prev["end"]) - start) <= 0.04 and a > float(prev["end"]):
                prev["end"] = round(min(a, float(w["start"])), 4)
            elif float(prev["end"]) > a >= float(prev["start"]) + 0.04:
                prev["end"] = round(min(a, float(w["start"])), 4)
    return refined


def reconcile_asr_onsets(words: list[dict[str, Any]], asr_words: list[dict[str, Any]],
                         audio: Any, sr: int) -> list[dict[str, Any]]:
    """Reconcile a large onset disagreement only when a real pause supports it.

    The separate ASR pass may detect a pause that forced text alignment joined
    to the previous word. Unmatched ASR words are ignored, never interpolated.
    """
    import numpy as np

    updated = [dict(w) for w in words]
    expected = [_canonical(w["word"]) for w in words]
    recognized = [_canonical(w["word"]) for w in asr_words]
    framesize = max(1, round(sr * 0.01))
    y = np.asarray(audio, dtype=np.float32).reshape(-1)
    count = len(y) // framesize
    if count < 8:
        return updated
    rms = np.sqrt(np.mean(y[:count * framesize].reshape(count, framesize) ** 2, axis=1) + 1e-12)
    threshold = max(0.0025, float(np.percentile(rms, 90)) * 0.025)
    for block in SequenceMatcher(None, expected, recognized, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            i, j = block.a + offset, block.b + offset
            original = float(updated[i]["start"])
            observed = float(asr_words[j]["start"])
            if not (0.12 <= observed - original <= 0.35):
                continue
            left, right = max(0, round(original * 100)), min(count, round((observed + 0.03) * 100))
            quiet = rms[left:right] < threshold
            best = None
            q = 0
            while q < len(quiet):
                if not quiet[q]:
                    q += 1
                    continue
                e = q + 1
                while e < len(quiet) and quiet[e]:
                    e += 1
                if e - q >= 6:
                    best = ((left + q) / 100.0, (left + e) / 100.0)
                q = e
            if best is None or abs(best[1] - observed) > 0.08:
                continue
            a, b = best
            new_start = max(original, min(observed - 0.02, float(updated[i]["end"]) - 0.06))
            if new_start <= original:
                continue
            updated[i]["start"] = round(new_start, 4)
            updated[i]["asr_refined_from"] = round(original, 4)
            if i and abs(float(updated[i - 1]["end"]) - original) <= 0.04:
                updated[i - 1]["end"] = round(min(a, new_start), 4)
    return updated


def validate_alignment(subs: Iterable[Any], alignment: dict[str, Any],
                       duration: float, audio_path: str | Path | None = None) -> None:
    expected = transcript_of_subtitles(subs).split()
    words = alignment.get("words")
    if not isinstance(words, list) or len(words) != len(expected):
        raise AlignmentError(f"Altyazı ile ses kelime sayısı uyuşmuyor: {len(expected)}")
    if not math.isfinite(duration) or duration <= 0:
        raise AlignmentError("Ses süresi geçersiz")
    if audio_path is not None:
        digest = alignment.get("audio_sha256")
        if not digest or digest != digest_file(audio_path):
            raise AlignmentError("Kelime zamanları başka bir ses kaydına ait")
    prev_end = 0.0
    for expected_word, item in zip(expected, words):
        if _canonical(expected_word) != _canonical(str(item.get("word", ""))):
            raise AlignmentError(f"Yanlış kelime sırası: {expected_word!r} / {item.get('word')!r}")
        start, end = float(item.get("start", -1)), float(item.get("end", -1))
        if not (math.isfinite(start) and math.isfinite(end)):
            raise AlignmentError("Sonlu olmayan sözcük zamanı")
        if start < -0.001 or end <= start or end > duration + 0.04:
            raise AlignmentError(f"Ses süresi dışında sözcük: {expected_word!r} [{start}, {end}]")
        if start < prev_end - 0.025:
            raise AlignmentError(f"Çakışan veya ters sıralı sözcük: {expected_word!r}")
        prev_end = end


class KaraokeAligner:
    """Reusable open-source Whisper alignment; one instance for all scenes."""

    def __init__(self, model_name: str = "small", *, cpu_threads: int = 2,
                 download_root: str | None = None, local_files_only: bool = False):
        try:
            from faster_whisper import WhisperModel
            from faster_whisper.tokenizer import Tokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Kelime-ses hizalaması için faster-whisper ve requirements-karaoke.txt "
                "bağımlılıklarını kurun; statik veya tahmini altyazıya geri dönülmez."
            ) from exc
        self.model_name = model_name
        self.model = WhisperModel(
            model_name, device="cpu", compute_type="int8", cpu_threads=cpu_threads,
            download_root=download_root, local_files_only=local_files_only,
        )
        self.tokenizer = Tokenizer(
            self.model.hf_tokenizer, self.model.model.is_multilingual,
            task="transcribe", language="tr",
        )

    def align(self, audio_path: str | Path, subs: Iterable[Any], *, verify_asr: bool = True) -> dict[str, Any]:
        import numpy as np
        import soundfile as sf
        from faster_whisper.audio import pad_or_trim
        from faster_whisper.transcribe import merge_punctuations

        audio_path = Path(audio_path)
        text = transcript_of_subtitles(subs)
        audio, sr = sf.read(str(audio_path), dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)
        duration = len(audio) / float(sr)
        if duration <= 0 or duration > 29.9:
            raise AlignmentError("Hizalama için ses sahnelerini 30 saniyenin altında tutun")
        # Interpolation is only used to resample the waveform, NEVER to time the
        # words. The words themselves are aligned to real acoustic features.
        if sr != 16000:
            samples = np.arange(round(len(audio) * 16000 / sr)) / 16000.0
            audio = np.interp(samples, np.arange(len(audio)) / float(sr), audio).astype("float32")
        expected = text.split()
        features = self.model.feature_extractor(audio)
        n_frames = features.shape[-1] - 1
        encoded = self.model.encode(pad_or_trim(features))
        tokens = self.tokenizer.encode(" " + text)
        if len(tokens) > 400:
            raise AlignmentError("Ses/metin sahnesi çok uzun; sahneyi bölün")
        raw = self.model.find_alignment(self.tokenizer, [tokens], encoded, n_frames)[0]
        merge_punctuations(raw, "\"'“¿([{-", "\"'.。,，!！?？:：”)]}、")
        words = merge_alignment_words(raw, expected)
        words = refine_pauses(words, audio, 16000)
        recognized, ratio, asr_words = "", None, []
        if verify_asr:
            segments, _info = self.model.transcribe(
                audio, language="tr", beam_size=5, condition_on_previous_text=False,
                vad_filter=False, word_timestamps=True,
            )
            segments = list(segments)
            recognized = " ".join(segment.text.strip() for segment in segments).strip()
            asr_words = [
                {"word": w.word.strip(), "start": round(float(w.start), 4),
                 "end": round(float(w.end), 4)}
                for segment in segments for w in (segment.words or []) if w.word.strip()
            ]
            ratio = round(SequenceMatcher(None, _canonical(text), _canonical(recognized)).ratio(), 4)
            if ratio < 0.80:
                raise AlignmentError(f"Ses ile altyazı metni uyuşmuyor (ASR benzerliği {ratio:.2f})")
            words = reconcile_asr_onsets(words, asr_words, audio, 16000)
        result = {
            "schema": "bilgi-dozu-karaoke-word-times-v1",
            "language": "tr",
            "model": "Systran/faster-whisper-" + self.model_name,
            "method": "known-text Whisper cross-attention + waveform silence-onset refinement",
            "approximate": True,
            "audio_sha256": digest_file(audio_path),
            "audio_duration_seconds": round(duration, 4),
            "transcript": text,
            "asr_transcript": recognized,
            "asr_similarity": ratio,
            "asr_words": asr_words,
            "words": words,
        }
        validate_alignment(subs, result, duration, audio_path)
        return result


def subtitle_groups(subs: Iterable[Any], alignment: dict[str, Any],
                    voice_start: float, duration: float) -> list[dict[str, Any]]:
    """Return group and individual-word time intervals for the frame renderer."""
    subs = list(subs)
    validate_alignment(subs, alignment, duration)
    words = alignment["words"]
    groups = []
    k = 0
    for i, group in enumerate(subs):
        text = group if isinstance(group, str) else group[0]
        n = len(text.split())
        current = words[k:k + n]
        start = voice_start if i == 0 else voice_start + current[0]["start"]
        end = (voice_start + words[k + n]["start"] if k + n < len(words)
               else min(voice_start + duration, voice_start + current[-1]["end"] + 0.12))
        groups.append({
            "text": text,
            "start": start,
            "end": end,
            "words": [
                {"word": item["word"], "start": voice_start + item["start"],
                 "end": voice_start + item["end"], "index": j}
                for j, item in enumerate(current)
            ],
        })
        k += n
    return groups


def active_word_at(group: dict[str, Any], time_s: float) -> int | None:
    """Only the word being spoken is yellow; pauses and other words are white."""
    if not (group["start"] <= time_s < group["end"]):
        return None
    for w in group["words"]:
        if w["start"] <= time_s < w["end"]:
            return int(w["index"])
    return None
