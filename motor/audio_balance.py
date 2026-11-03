"""Voice-relative background-music mixing for Bilgi Dozu production.

The old mixer applied a fixed -18 dB gain to whatever music file it received.
That is not the same thing as keeping the music 2 dB below the narration: the
source tracks can have different loudness.  Here speech and equalised music are
measured separately before mixing.  The unfaded, unducked music baseline is
2 LU below active narration, the loudness-domain interpretation of the requested
"two points lower".  A speech-driven sidechain automatically ducks the music
further when the narrator speaks and smoothly releases it during pauses.
Fades and safety limiting also affect the instantaneous difference.  The final
loudness should still be checked by ear.

Uses only the standard library and a local FFmpeg with loudnorm and alimiter.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

VOICE_TARGET_LUFS = -18.0
MUSIC_BELOW_VOICE_LU = 2.0
MASTER_TARGET_LUFS = -14.0
TRUE_PEAK_CEILING_DB = -1.0
DUCKING_THRESHOLD = 0.030       # linear amplitude, about -30.5 dBFS
DUCKING_RATIO = 8.0
DUCKING_ATTACK_MS = 18.0
DUCKING_RELEASE_MS = 550.0
DUCKING_KNEE = 2.0
MUSIC_EQ = "equalizer=f=2200:t=q:w=1.2:g=-3.5"
AUDIO_FORMAT = "aformat=sample_rates=44100:channel_layouts=stereo"


def ffmpeg_executable() -> str:
    """Prefer an explicit binary, then the system installation, then imageio."""
    explicit = os.environ.get("FFMPEG_BINARY")
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        found = shutil.which(explicit)
        if found:
            return found
        raise RuntimeError(f"FFMPEG_BINARY is not executable: {explicit}")
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError("FFmpeg is required; install ffmpeg or set FFMPEG_BINARY") from exc


def _run(args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(f"FFmpeg exited {result.returncode}: {result.stderr[-2500:]}")
    return result


def measure_loudness(path: str, *, duration: float | None = None,
                     filters: str = "", loop: bool = False) -> dict[str, float]:
    """Measure BS.1770 integrated LUFS and true peak after requested filters."""
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise ValueError("duration must be positive and finite")
    parts: list[str] = []
    if duration is not None:
        parts.extend([f"atrim=0:{duration:.6f}", "asetpts=PTS-STARTPTS"])
    parts.append(AUDIO_FORMAT)
    if filters:
        parts.append(filters)
    # The report describes the input to loudnorm; the temporary normalized
    # output goes to a null sink and is not used in the final mix.
    parts.append("loudnorm=I=-18:TP=-1:LRA=11:print_format=json")
    cmd = [ffmpeg_executable(), "-nostdin", "-hide_banner"]
    if loop:
        cmd += ["-stream_loop", "-1"]
    cmd += ["-i", str(path), "-map", "0:a:0", "-vn", "-sn", "-dn",
            "-af", ",".join(parts), "-f", "null", "-"]
    output = _run(cmd).stderr
    blocks = re.findall(r"\{[^{}]*\}", output, flags=re.DOTALL)
    for block in reversed(blocks):
        try:
            values = json.loads(block)
            if "input_i" in values and "input_tp" in values:
                integrated = float(values["input_i"])
                peak = float(values["input_tp"])
                if not (math.isfinite(integrated) and math.isfinite(peak)) or integrated <= -69.0:
                    raise ValueError(f"Cannot normalize silent or too-short audio: {path}")
                return {"lufs": integrated, "true_peak_db": peak}
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"Could not read loudness measurements for {path}: {output[-1200:]}")


def mix_speech_and_music(
    scenes_meta: list[dict[str, Any]],
    music_path: str,
    total_dur: float,
    out_wav: str,
    *,
    voice_target_lufs: float = VOICE_TARGET_LUFS,
    music_below_voice_lu: float = MUSIC_BELOW_VOICE_LU,
    master_target_lufs: float = MASTER_TARGET_LUFS,
    peak_ceiling_db: float = TRUE_PEAK_CEILING_DB,
    fade_in: float = 0.6,
    fade_out: float = 3.0,
    ducking: bool = True,
    diagnostic_ducked_music_path: str | None = None,
) -> dict[str, Any]:
    """Mix source speech and music without editing source files.

    Every narration segment is measured individually.  The un-faded, un-ducked
    EQ'd music baseline targets 2 LU below narration. A voice-driven sidechain
    then lowers the music during speech and returns it smoothly during gaps.
    A shared safety reduction and linear mastering gain retain the time-varying
    ducking. Output is stereo 44.1 kHz PCM16. Music fades out for 3 seconds.
    The optional diagnostic file contains the music after ducking, before master.
    """
    if not scenes_meta:
        raise ValueError("At least one narration segment is required")
    if not math.isfinite(total_dur) or total_dur <= 0:
        raise ValueError("total_dur must be positive and finite")
    if not math.isfinite(music_below_voice_lu) or music_below_voice_lu < 0:
        raise ValueError("music_below_voice_lu must be non-negative")
    if not math.isfinite(voice_target_lufs) or not math.isfinite(master_target_lufs):
        raise ValueError("Loudness targets must be finite")
    if not -10.0 <= peak_ceiling_db < 0:
        raise ValueError("peak ceiling must be between -10 and 0 dBTP")
    if fade_in < 0 or fade_out < 0:
        raise ValueError("fade times must be non-negative")
    if Path(out_wav).resolve() == Path(music_path).resolve():
        raise ValueError("Output must not overwrite the music source")
    if diagnostic_ducked_music_path:
        diag = Path(diagnostic_ducked_music_path).resolve()
        protected = [Path(out_wav).resolve(), Path(music_path).resolve()]
        protected.extend(Path(s["vo_file"]).resolve() for s in scenes_meta)
        if diag in protected or diag.suffix.lower() != ".wav":
            raise ValueError("Diagnostic output must be a separate .wav file")
        diag.parent.mkdir(parents=True, exist_ok=True)

    readings: list[dict[str, float]] = []
    for scene in scenes_meta:
        start = float(scene["vo_start"])
        if not math.isfinite(start) or start < 0 or start >= total_dur:
            raise ValueError("Narration start must be inside the output duration")
        if Path(out_wav).resolve() == Path(scene["vo_file"]).resolve():
            raise ValueError("Output must not overwrite narration")
        readings.append(measure_loudness(str(scene["vo_file"])))
    music_reading = measure_loudness(music_path, duration=total_dur, filters=MUSIC_EQ, loop=True)

    music_target = voice_target_lufs - music_below_voice_lu
    voice_gains = [voice_target_lufs - r["lufs"] for r in readings]
    music_gain = music_target - music_reading["lufs"]

    worst_voice_peak = max(r["true_peak_db"] + gain for r, gain in zip(readings, voice_gains))
    music_peak = music_reading["true_peak_db"] + music_gain
    # Sum worst-case peaks in linear amplitude, not dB.  This is deliberately
    # conservative; it avoids clipping if speech and music peaks coincide.
    sum_peak_db = 20.0 * math.log10(10.0 ** (worst_voice_peak / 20.0) + 10.0 ** (music_peak / 20.0))
    common_reduction = max(0.0, sum_peak_db - peak_ceiling_db)
    voice_gains = [gain - common_reduction for gain in voice_gains]
    music_gain -= common_reduction

    inputs: list[str] = []
    filters: list[str] = []
    for i, (scene, gain) in enumerate(zip(scenes_meta, voice_gains)):
        inputs += ["-i", str(scene["vo_file"])]
        delay = max(0, int(round(float(scene["vo_start"]) * 1000.0)))
        filters.append(
            f"[{i}:a]{AUDIO_FORMAT},volume={gain:+.5f}dB,"
            f"adelay={delay}|{delay},apad=whole_dur={total_dur:.6f},"
            f"atrim=0:{total_dur:.6f}[v{i}]"
        )
    filters.append("".join(f"[v{i}]" for i in range(len(scenes_meta))) +
                   f"amix=inputs={len(scenes_meta)}:normalize=0:duration=longest[voices]")

    inputs += ["-stream_loop", "-1", "-i", str(music_path)]
    mi = len(scenes_meta)
    music_filters = [f"atrim=0:{total_dur:.6f}", "asetpts=PTS-STARTPTS", AUDIO_FORMAT,
                     MUSIC_EQ, f"volume={music_gain:+.5f}dB"]
    if fade_in:
        music_filters.append(f"afade=t=in:st=0:d={min(fade_in, total_dur):.6f}")
    if fade_out:
        fade_len = min(fade_out, total_dur)
        music_filters.append(f"afade=t=out:st={max(0.0, total_dur-fade_len):.6f}:d={fade_len:.6f}")
    filters.append(f"[{mi}:a]" + ",".join(music_filters) + "[music]")
    if ducking:
        # Main input is music; the second input is the actual narration.  Do
        # not compress the narration itself.  A slow release avoids pumping
        # between adjacent words while recovering the music during real pauses.
        filters.append("[voices]asplit=2[voice_main][voice_key]")
        filters.append(
            "[music][voice_key]sidechaincompress="
            f"threshold={DUCKING_THRESHOLD:.6f}:ratio={DUCKING_RATIO:.3f}:"
            f"attack={DUCKING_ATTACK_MS:.3f}:release={DUCKING_RELEASE_MS:.3f}:"
            f"knee={DUCKING_KNEE:.3f}:detection=rms:link=maximum:"
            "makeup=1:level_sc=1:mix=1[music_controlled]"
        )
    else:
        filters.append("[voices]anull[voice_main]")
        filters.append("[music]anull[music_controlled]")
    if diagnostic_ducked_music_path:
        filters.append("[music_controlled]asplit=2[music_mix][music_diagnostic]")
    else:
        filters.append("[music_controlled]anull[music_mix]")
    limit = 10.0 ** (peak_ceiling_db / 20.0)
    filters.append(
        "[voice_main][music_mix]amix=inputs=2:normalize=0:duration=longest,"
        f"alimiter=limit={limit:.6f}:level=disabled:latency=1[aout]"
    )

    Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
    # Measure the combined mix, then apply one shared linear gain.  This
    # improves overall consistency without changing the chosen stem balance.
    with tempfile.TemporaryDirectory(prefix="bd_audio_") as tmpdir:
        premix = str(Path(tmpdir) / "premix.wav")
        command = [ffmpeg_executable(), "-nostdin", "-y", "-hide_banner", "-loglevel", "error"]
        command += inputs + ["-filter_complex", ";".join(filters), "-map", "[aout]", "-t", f"{total_dur:.6f}",
                             "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", premix]
        if diagnostic_ducked_music_path:
            command += ["-map", "[music_diagnostic]", "-t", f"{total_dur:.6f}", "-ar", "44100", "-ac", "2",
                        "-c:a", "pcm_s16le", str(diagnostic_ducked_music_path)]
        _run(command)
        premix_reading = measure_loudness(premix)
        wanted_master_gain = master_target_lufs - premix_reading["lufs"]
        # Leave a little margin for rounding and later AAC encoding.
        max_safe_gain = peak_ceiling_db - premix_reading["true_peak_db"] - 0.15
        master_gain = min(wanted_master_gain, max_safe_gain)
        command = [ffmpeg_executable(), "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
                   "-i", premix, "-af", f"volume={master_gain:+.5f}dB", "-ar", "44100", "-ac", "2",
                   "-c:a", "pcm_s16le", str(out_wav)]
        _run(command)
    final_reading = measure_loudness(out_wav)
    return {
        "voice_inputs": readings,
        "music_input_after_eq": music_reading,
        "voice_gain_db_before_master": voice_gains,
        "music_gain_db_before_master": music_gain,
        "voice_target_after_master_lufs": voice_target_lufs - common_reduction + master_gain,
        "music_target_before_fades_after_master_lufs": music_target - common_reduction + master_gain,
        "music_below_voice_lu": music_below_voice_lu,
        "ducking_enabled": ducking,
        "ducking_threshold_linear": DUCKING_THRESHOLD if ducking else None,
        "ducking_ratio": DUCKING_RATIO if ducking else None,
        "ducking_attack_ms": DUCKING_ATTACK_MS if ducking else None,
        "ducking_release_ms": DUCKING_RELEASE_MS if ducking else None,
        "diagnostic_ducked_music_path": diagnostic_ducked_music_path,
        "common_headroom_db": common_reduction,
        "shared_master_gain_db": master_gain,
        "master_target_lufs": master_target_lufs,
        "final_mix_loudness": final_reading,
        "peak_ceiling_db": peak_ceiling_db,
        "fade_in_s": min(fade_in, total_dur),
        "fade_out_s": min(fade_out, total_dur),
        "duration_s": total_dur,
        "out_wav": str(out_wav),
    }
