import wave
import numpy as np

MOOD_PRESETS = {
    "noroloji_gizem": {
        "bpm": 72,
        "chords": [146.83, 174.61, 220.00, 261.63],   # D minor7 mysterious glass pad
        "arp":    [293.66, 349.23, 440.00, 466.16, 440.00, 349.23, 329.63, 293.66],
        "sfx":    "neural_spark"
    },
    "tibbi_refleks": {
        "bpm": 92,
        "chords": [92.50, 138.59, 185.00, 220.00],    # F# minor tense pulse
        "arp":    [369.99, 440.00, 554.37, 493.88, 440.00, 369.99, 329.63, 369.99],
        "sfx":    "heartbeat_pulse"
    },
    "doga_kesif": {
        "bpm": 78,
        "chords": [155.56, 196.00, 233.08, 293.66],   # Eb major7 celestial wonder
        "arp":    [311.13, 392.00, 466.16, 587.33, 466.16, 392.00, 349.23, 392.00],
        "sfx":    "crystal_drop"
    },
    "gunluk_yanilgi": {
        "bpm": 86,
        "chords": [110.00, 164.81, 196.00, 246.94],   # A minor9 warm marimba groove
        "arp":    [220.00, 261.63, 329.63, 392.00, 329.63, 293.66, 261.63, 246.94],
        "sfx":    "soft_whoosh"
    },
    "mikro_bilim": {
        "bpm": 82,
        "chords": [98.00, 146.83, 174.61, 220.00],    # G dorian clean modular lab
        "arp":    [293.66, 392.00, 440.00, 523.25, 440.00, 392.00, 349.23, 293.66],
        "sfx":    "optic_chime"
    },
}

def generate_topic_bgm(out_wav, mood="noroloji_gizem", semitone_shift=0, duration_sec=190.0, add_opening_sfx=True):
    """Generates a unique topic-matched stereo 44.1kHz ambient soundtrack + subtle 00:00 hook micro-SFX."""
    sr = 44100
    preset = MOOD_PRESETS.get(mood, MOOD_PRESETS["noroloji_gizem"])
    ratio = 2.0 ** (semitone_shift / 12.0)
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False, dtype=np.float32)

    c0, c1, c2, c3 = [f * ratio for f in preset["chords"]]
    ch_l = (
        0.25 * np.sin(2 * np.pi * c0 * t) +
        0.18 * np.sin(2 * np.pi * c1 * t + 0.35 * np.sin(2 * np.pi * 0.07 * t)) +
        0.13 * np.sin(2 * np.pi * c2 * t) * (0.65 + 0.35 * np.sin(2 * np.pi * 0.10 * t)) +
        0.09 * np.sin(2 * np.pi * c3 * t) * (0.55 + 0.45 * np.cos(2 * np.pi * 0.08 * t))
    )
    ch_r = (
        0.25 * np.sin(2 * np.pi * c0 * t) +
        0.18 * np.sin(2 * np.pi * c1 * t - 0.35 * np.sin(2 * np.pi * 0.07 * t)) +
        0.13 * np.sin(2 * np.pi * c2 * t) * (0.65 + 0.35 * np.cos(2 * np.pi * 0.10 * t)) +
        0.09 * np.sin(2 * np.pi * c3 * t) * (0.55 + 0.45 * np.sin(2 * np.pi * 0.08 * t))
    )

    step_dur = 60.0 / float(preset["bpm"]) / 2.0
    beat = t % step_dur
    arp_notes = np.array([f * ratio for f in preset["arp"]], dtype=np.float32)
    n_idx = (np.floor(t / step_dur).astype(np.int32)) % len(arp_notes)
    freqs = arp_notes[n_idx]
    ping = 0.085 * np.exp(-beat * 6.8) * np.sin(2 * np.pi * freqs * beat)

    ch_l = (ch_l + ping * 0.90) * 0.84
    ch_r = (ch_r + np.roll(ping, int(0.017 * sr)) * 0.90) * 0.84

    if add_opening_sfx:
        # Subtle 0.42s micro-SFX hook at t=0.05..0.47s. Overall music is
        # measured and balanced relative to narration by audio_balance.py.
        n_sfx = int(0.42 * sr)
        ts = np.linspace(0, 0.42, n_sfx, dtype=np.float32)
        kind = preset["sfx"]
        if kind == "neural_spark":
            sfx = 0.32 * np.exp(-ts * 9.0) * np.sin(2 * np.pi * (520.0 + 480.0 * ts) * ts)
        elif kind == "heartbeat_pulse":
            sfx = 0.38 * (np.exp(-((ts - 0.07) ** 2) / 0.0008) + 0.7 * np.exp(-((ts - 0.23) ** 2) / 0.001)) * np.sin(2 * np.pi * 68.0 * ts)
        elif kind == "crystal_drop":
            sfx = 0.30 * np.exp(-ts * 8.5) * np.sin(2 * np.pi * (680.0 + 360.0 * np.exp(-ts * 12.0)) * ts)
        else:
            sfx = 0.28 * np.exp(-ts * 8.0) * np.sin(2 * np.pi * 440.0 * ratio * ts)
        i0 = int(0.05 * sr)
        ch_l[i0:i0+n_sfx] += sfx
        ch_r[i0:i0+n_sfx] += sfx

    stereo = np.clip(np.stack([ch_l, ch_r], axis=-1), -0.95, 0.95)
    with wave.open(out_wav, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((stereo * 32767.0).astype(np.int16).tobytes())
    return out_wav
