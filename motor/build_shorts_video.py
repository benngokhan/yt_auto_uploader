import os
import json
import subprocess
import time
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1920
FPS = 60
CROSS_DISSOLVE = 0.50  # seconds

FONT_BLACK_PATH = "/home/user/assets/fonts/Montserrat-Black.ttf"
FONT_BOLD_PATH = "/home/user/assets/fonts/Montserrat-Bold.ttf"
EMOJI_FONT_PATH = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

WHITE = (255, 255, 255, 255)
YELLOW = (255, 214, 0, 255)       # #FFD600 — ADIM 6 Sarı vurgu
LIME = (220, 255, 46, 255)        # @bilgidozuofficial imza neon-sarı rozet/bar rengi
DARK_INK = (10, 18, 24, 255)

# 1. Read exact clean speech durations
vo_files = [f"/home/user/assets/vo_clean/scene_{i:02d}.wav" for i in range(1, 7)]
vo_durs = []
for vf in vo_files:
    out = subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", vf]
    ).decode()
    vo_durs.append(float(json.loads(out)["format"]["duration"]))

# Build exact master timeline
LEAD_IN = 0.20
GAP = 0.30
TAIL_OUT = 0.80

scenes_meta = []
cursor = 0.0
for idx, vd in enumerate(vo_durs):
    s_start = cursor
    vo_start = s_start + (LEAD_IN if idx == 0 else GAP / 2.0)
    vo_end = vo_start + vd
    if idx < 5:
        s_end = vo_end + GAP / 2.0
    else:
        s_end = vo_end + TAIL_OUT
    scenes_meta.append({
        "index": idx + 1,
        "scene_start": s_start,
        "scene_end": s_end,
        "vo_start": vo_start,
        "vo_end": vo_end,
        "vo_dur": vd,
        "vo_file": vo_files[idx],
    })
    cursor = s_end

TOTAL_DUR = scenes_meta[-1]["scene_end"]
TOTAL_FRAMES = int(round(TOTAL_DUR * FPS))
print(f"Total video duration: {TOTAL_DUR:.3f}s ({TOTAL_FRAMES} frames @ {FPS}fps)")
for sm in scenes_meta:
    print(
        f"  Scene {sm['index']}: visual [{sm['scene_start']:.2f}s - {sm['scene_end']:.2f}s] "
        f"(len={sm['scene_end']-sm['scene_start']:.2f}s) | VO [{sm['vo_start']:.2f}s - {sm['vo_end']:.2f}s]"
    )

# 2. Scene definitions: image, Ken Burns motion, ADIM 6 upper overlay, dynamic subtitles
scene_configs = [
    {
        "img": "/home/user/assets/scene_01_hook.png",
        "zoom": (1.00, 1.14),
        "pan_x": (0.0, 0.0),
        "pan_y": (24.0, -24.0),
        "emoji": "❓",
        "title_line1": "SUDA PARMAKLAR",
        "title_line2": "NEDEN BURUŞUR?",
        "subs": [
            ("Duşta ya da denizde kaldığında", []),
            ("parmak uçların neden buruşur?", ["neden", "buruşur?"]),
            ("Çoğu kişi derinin suyu emip\nşiştiğini sanır ama yanılıyor.", ["şiştiğini", "yanılıyor."]),
        ],
    },
    {
        "img": "/home/user/assets/scene_02_mechanism.png",
        "zoom": (1.00, 1.13),
        "pan_x": (-20.0, 20.0),
        "pan_y": (12.0, -12.0),
        "emoji": "💡",
        "title_line1": "SU EMİLİMİ DEĞİL:",
        "title_line2": "BEYİN EMRİ!",
        "subs": [
            ("Cevap aslında beyninde gizli.", ["beyninde", "gizli."]),
            ("Ter gözeneklerinden sızan su\ntuz oranını düşürünce,", ["tuz", "oranını"]),
            ("sinirler sinyal gönderip\ndamarları büzer.", ["sinyal", "damarları", "büzer."]),
        ],
    },
    {
        "img": "/home/user/assets/scene_03_microscopic.png",
        "zoom": (1.00, 1.15),
        "pan_x": (0.0, 0.0),
        "pan_y": (18.0, -18.0),
        "emoji": "🔬",
        "title_line1": "PARMAK İZİ GİBİ",
        "title_line2": "AYNI DESEN!",
        "subs": [
            ("Ama asıl ilginç olan şu:", ["ilginç"]),
            ("Daralan damarlar deriyi çekip\nsu tahliye olukları açar", ["su", "tahliye", "olukları"]),
            ("ve bu desen her seferinde\naynı oluşur.", ["her", "seferinde", "aynı"]),
        ],
    },
    {
        "img": "/home/user/assets/scene_04_wow.png",
        "zoom": (1.00, 1.13),
        "pan_x": (16.0, -16.0),
        "pan_y": (22.0, -22.0),
        "emoji": "⚡",
        "title_line1": "SİNİR KESİKSE",
        "title_line2": "BURUŞMA SIFIR!",
        "subs": [
            ("Peki bunu biliyor muydun?", ["biliyor", "muydun?"]),
            ("Parmağındaki siniri hasarlı birinin\nelini saatlerce suda tutsan bile", ["siniri", "hasarlı", "saatlerce"]),
            ("derisi tek çizgi bile buruşmaz!", ["tek", "çizgi", "buruşmaz!"]),
        ],
    },
    {
        "img": "/home/user/assets/scene_05_dailylife.png",
        "zoom": (1.00, 1.12),
        "pan_x": (-15.0, 15.0),
        "pan_y": (-18.0, 18.0),
        "emoji": "🌍",
        "title_line1": "OTOMATİK TUTUŞ:",
        "title_line2": "YAĞMUR LASTİĞİ (%12+)",
        "subs": [
            ("Yani ıslak bir bardağı tuttuğunda", ["ıslak", "bardağı"]),
            ("vücudunda yağmur lastiği\nrefleksi çalışıyor", ["yağmur", "lastiği", "refleksi"]),
            ("ve kavrama hızın\nyüzde on iki artıyor.", ["yüzde", "on", "iki", "artıyor."]),
        ],
    },
    {
        "img": "/home/user/assets/scene_06_cta.png",
        "zoom": (1.01, 1.13),
        "pan_x": (14.0, -14.0),
        "pan_y": (20.0, -20.0),
        "emoji": "👇",
        "title_line1": "SENDE KAÇ DK SÜRÜYOR?",
        "title_line2": "YORUMA YAZ & ABONE OL!",
        "subs": [
            ("Senin de başına geldi mi?", ["başına", "geldi", "mi?"]),
            ("Sonraki videoda dirseğini çarpınca", ["dirseğini", "çarpınca"]),
            ("neden elektrik çarptığını\ninceliyoruz, kaçırma!", ["elektrik", "çarptığını", "kaçırma!"]),
        ],
    },
]

# 3. Pre-load & apply Teal-Orange Cinematic LUT + subtle top/bottom scrim to 6 high-res images
UPS_W, UPS_H = 1350, 2400  # 1.25x oversampled 9:16 canvas for razor-sharp Ken Burns

def apply_teal_orange_cinematic(bgr_img):
    # bgr float [0, 1]
    f = bgr_img.astype(np.float32) / 255.0
    b, g, r = f[:, :, 0], f[:, :, 1], f[:, :, 2]
    lum = 0.114 * b + 0.587 * g + 0.299 * r

    # Shadows/low-mids -> cool deep teal; Highlights -> warm cinematic amber-orange
    shadow_w = np.clip(1.0 - lum * 1.6, 0.0, 1.0)
    high_w = np.clip((lum - 0.35) * 1.5, 0.0, 1.0)

    r_new = r - 0.045 * shadow_w + 0.065 * high_w
    g_new = g + 0.012 * shadow_w + 0.015 * high_w
    b_new = b + 0.055 * shadow_w - 0.050 * high_w

    graded = np.stack([b_new, g_new, r_new], axis=-1)
    # Gentle S-curve contrast (+6%)
    graded = np.clip((graded - 0.5) * 1.06 + 0.5, 0.0, 1.0)
    return (graded * 255.0).astype(np.uint8)

prepared_imgs = []
for cfg in scene_configs:
    pil_im = Image.open(cfg["img"]).convert("RGB")
    # Center-crop cleanly to exact 9:16 before Lanczos resize to 1350x2400
    iw, ih = pil_im.size
    target_ratio = 9.0 / 16.0
    cur_ratio = iw / ih
    if cur_ratio > target_ratio:
        new_w = int(ih * target_ratio)
        off = (iw - new_w) // 2
        pil_im = pil_im.crop((off, 0, off + new_w, ih))
    elif cur_ratio < target_ratio:
        new_h = int(iw / target_ratio)
        off = (ih - new_h) // 2
        pil_im = pil_im.crop((0, off, iw, off + new_h))
    pil_im = pil_im.resize((UPS_W, UPS_H), Image.Resampling.LANCZOS)
    bgr = cv2.cvtColor(np.array(pil_im), cv2.COLOR_RGB2BGR)
    bgr = apply_teal_orange_cinematic(bgr)
    prepared_imgs.append(bgr)

# Precompute top & bottom subtle legibility gradient mask for 1080x1920 frame
scrim = np.ones((H, W, 1), dtype=np.float32)
top_y = np.linspace(0, 1, 460, dtype=np.float32)[:, None]
scrim[:460, :, 0] = 0.52 + 0.48 * (top_y ** 1.4)
bot_y = np.linspace(1, 0, 320, dtype=np.float32)[:, None]
scrim[H - 320 :, :, 0] = 0.48 + 0.52 * (bot_y ** 1.3)

# 4. Helper functions to render crisp RGBA overlays with Montserrat + NotoColorEmoji
def render_emoji_icon(emoji_char, target_px=64):
    efont = ImageFont.truetype(EMOJI_FONT_PATH, 109)
    canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.text((16, 16), emoji_char, font=efont, embedded_color=True)
    bbox = canvas.getbbox()
    if bbox:
        canvas = canvas.crop(bbox)
    w0, h0 = canvas.size
    scale = target_px / max(w0, h0, 1)
    return canvas.resize((max(1, int(w0 * scale)), max(1, int(h0 * scale))), Image.Resampling.LANCZOS)

def fit_font(path, text, max_width, start_size, min_size=28):
    sz = start_size
    while sz >= min_size:
        f = ImageFont.truetype(path, sz)
        bbox = f.getbbox(text)
        if (bbox[2] - bbox[0]) <= max_width:
            return f
        sz -= 2
    return ImageFont.truetype(path, min_size)

def make_upper_title_band(emoji_char, line1, line2):
    """Returns RGBA band of shape (300, 1080, 4) placed at y_offset = 155."""
    band_h = 300
    txt_layer = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    shadow_layer = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    d_txt = ImageDraw.Draw(txt_layer)
    d_sh = ImageDraw.Draw(shadow_layer)

    em_img = render_emoji_icon(emoji_char, target_px=56)
    ew, eh = em_img.size

    max_w1 = W - 150 - (ew + 18)
    f1 = fit_font(FONT_BLACK_PATH, line1, max_w1, start_size=54)
    f2 = fit_font(FONT_BLACK_PATH, line2, W - 140, start_size=58)

    b1 = f1.getbbox(line1)
    w1, h1 = b1[2] - b1[0], b1[3] - b1[1]
    total_row1_w = ew + 18 + w1
    x1_start = (W - total_row1_w) // 2
    y1 = 28

    # Paste emoji shadow + emoji
    em_shadow = Image.new("RGBA", em_img.size, (0, 0, 0, 220))
    shadow_layer.paste(em_shadow, (x1_start, y1 + 6), em_img)
    txt_layer.paste(em_img, (x1_start, y1), em_img)

    tx1 = x1_start + ew + 18
    ty1 = y1 + (eh - h1) // 2 - b1[1]
    d_sh.text((tx1, ty1 + 6), line1, font=f1, fill=(0, 0, 0, 235), stroke_width=6, stroke_fill=(0, 0, 0, 220))
    d_txt.text((tx1, ty1), line1, font=f1, fill=WHITE, stroke_width=2, stroke_fill=(0, 0, 0, 180))

    b2 = f2.getbbox(line2)
    w2, h2 = b2[2] - b2[0], b2[3] - b2[1]
    tx2 = (W - w2) // 2
    ty2 = y1 + max(eh, h1) + 20 - b2[1]
    d_sh.text((tx2, ty2 + 6), line2, font=f2, fill=(0, 0, 0, 240), stroke_width=7, stroke_fill=(0, 0, 0, 230))
    d_txt.text((tx2, ty2), line2, font=f2, fill=YELLOW, stroke_width=2, stroke_fill=(0, 0, 0, 190))

    shadow_blurred = shadow_layer.filter(ImageFilter.GaussianBlur(radius=9))
    combined = Image.alpha_composite(shadow_blurred, txt_layer)
    # Convert RGB->BGRA for direct OpenCV blending
    arr = np.array(combined)
    bgra = arr[:, :, [2, 1, 0, 3]].copy()
    return bgra  # y=155..455

def make_subtitle_band(text_multiline, highlight_words):
    """Returns BGRA band of shape (240, 1080, 4) placed at y_offset = 1250."""
    band_h = 240
    txt_layer = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    sh_layer = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    d_txt = ImageDraw.Draw(txt_layer)
    d_sh = ImageDraw.Draw(sh_layer)

    lines = text_multiline.split("\n")
    font = ImageFont.truetype(FONT_BOLD_PATH, 40)
    # Check width fit
    for ln in lines:
        if (font.getbbox(ln)[2] - font.getbbox(ln)[0]) > (W - 130):
            font = ImageFont.truetype(FONT_BOLD_PATH, 35)
            break

    hl_set = {w.lower().strip(",.!?:;") for w in highlight_words}
    line_h = 54
    start_y = (band_h - len(lines) * line_h) // 2

    for li, ln in enumerate(lines):
        words = ln.split(" ")
        space_w = font.getlength(" ")
        word_widths = [font.getlength(w) for w in words]
        total_w = sum(word_widths) + space_w * max(0, len(words) - 1)
        cx = (W - total_w) / 2.0
        cy = start_y + li * line_h
        for w, ww in zip(words, word_widths):
            clean_w = w.lower().strip(",.!?:;")
            col = YELLOW if clean_w in hl_set else WHITE
            d_sh.text((cx, cy + 4), w, font=font, fill=(0, 0, 0, 235), stroke_width=6, stroke_fill=(0, 0, 0, 220))
            d_txt.text((cx, cy), w, font=font, fill=col, stroke_width=2, stroke_fill=(0, 0, 0, 185))
            cx += ww + space_w

    sh_blur = sh_layer.filter(ImageFilter.GaussianBlur(radius=7))
    comb = Image.alpha_composite(sh_blur, txt_layer)
    arr = np.array(comb)
    return arr[:, :, [2, 1, 0, 3]].copy()

def make_static_brand_layers():
    """Top BİLGİ DOZU pill (y=80..150) + Bottom source & BİLGİ DOZU logo (y=1735..1875)."""
    top_band = Image.new("RGBA", (W, 80), (0, 0, 0, 0))
    dt = ImageDraw.Draw(top_band)
    # Neon lime rounded pill at x=72, y=14..58
    pill_box = (72, 14, 276, 58)
    dt.rounded_rectangle(pill_box, radius=22, fill=LIME)
    fpill = ImageFont.truetype(FONT_BLACK_PATH, 22)
    b = fpill.getbbox("BİLGİ DOZU")
    pw, ph = b[2] - b[0], b[3] - b[1]
    dt.text((72 + (204 - pw) // 2, 14 + (44 - ph) // 2 - b[1]), "BİLGİ DOZU", font=fpill, fill=DARK_INK)
    top_arr = np.array(top_band)[:, :, [2, 1, 0, 3]].copy()

    bot_band = Image.new("RGBA", (W, 150), (0, 0, 0, 0))
    db = ImageDraw.Draw(bot_band)
    fsmall = ImageFont.truetype(FONT_BOLD_PATH, 19)
    s1 = "*Görseller temsilîdir (AI bilimsel canlandırma)"
    s2 = "Kaynak: Binghamton Univ. (2025) & Biology Letters"
    for idx_s, st in enumerate([s1, s2]):
        sw = fsmall.getlength(st)
        db.text(((W - sw) / 2, 8 + idx_s * 25), st, font=fsmall, fill=(195, 212, 220, 175))

    flogo = ImageFont.truetype(FONT_BLACK_PATH, 34)
    w_b = flogo.getlength("BİLGİ ")
    w_d = flogo.getlength("DOZU")
    lx = (W - (w_b + w_d)) / 2
    ly = 74
    db.text((lx, ly), "BİLGİ ", font=flogo, fill=WHITE, stroke_width=2, stroke_fill=(0, 0, 0, 180))
    db.text((lx + w_b, ly), "DOZU", font=flogo, fill=LIME, stroke_width=2, stroke_fill=(0, 0, 0, 180))
    bot_arr = np.array(bot_band)[:, :, [2, 1, 0, 3]].copy()
    return top_arr, bot_arr

print("Pre-rendering text & brand overlays...")
top_brand_bgra, bot_brand_bgra = make_static_brand_layers()

upper_titles_bgra = []
sub_timeline = []  # list of (t_start, t_end, bgra_band)

for idx, (sm, cfg) in enumerate(zip(scenes_meta, scene_configs)):
    upper_titles_bgra.append(make_upper_title_band(cfg["emoji"], cfg["title_line1"], cfg["title_line2"]))
    # Distribute subtitle chunks proportionally across [vo_start, vo_end]
    subs = cfg["subs"]
    char_counts = [max(8, len(s[0])) for s in subs]
    tot_chars = sum(char_counts)
    cur_t = sm["vo_start"]
    for (stext, hl), cc in zip(subs, char_counts):
        seg_d = sm["vo_dur"] * (cc / tot_chars)
        band = make_subtitle_band(stext, hl)
        sub_timeline.append((cur_t, cur_t + seg_d, band))
        cur_t += seg_d

def blend_band_inplace(frame_bgr, y0, bgra_band, opacity=1.0):
    if opacity <= 0.005:
        return
    bh = bgra_band.shape[0]
    roi = frame_bgr[y0 : y0 + bh]
    alpha = (bgra_band[:, :, 3:4].astype(np.float32) / 255.0) * float(opacity)
    fg = bgra_band[:, :, :3].astype(np.float32)
    bg = roi.astype(np.float32)
    frame_bgr[y0 : y0 + bh] = (bg * (1.0 - alpha) + fg * alpha).astype(np.uint8)

def render_ken_burns(scene_idx, local_progress):
    """Smooth cosine-eased sub-pixel Ken Burns crop from 1350x2400 -> 1080x1920."""
    cfg = scene_configs[scene_idx]
    img = prepared_imgs[scene_idx]
    # Gentle smooth progression (70% linear + 30% cosine ease for continuous organic motion)
    p = max(0.0, min(1.0, local_progress))
    ease = 0.70 * p + 0.30 * (0.5 - 0.5 * np.cos(np.pi * p))
    z0, z1 = cfg["zoom"]
    px0, px1 = cfg["pan_x"]
    py0, py1 = cfg["pan_y"]
    zoom = z0 + (z1 - z0) * ease
    dx = px0 + (px1 - px0) * ease
    dy = py0 + (py1 - py0) * ease

    # Crop window size inside 1350x2400 (note 1350/1080 = 1.25 base headroom!)
    base_scale = W / float(UPS_W)  # 0.80
    eff_scale = base_scale * zoom   # output pixels per source pixel -> Wait:
    # We want zoomed IN as zoom increases: larger magnification = eff_scale = (W / UPS_W) * zoom?
    # Check: at zoom=1.0, source 1260x2240 maps to 1080x1920 (leaving margin for pan!).
    # At zoom=1.14, source (1260/1.14)x(2240/1.14) = 1105x1965 maps to 1080x1920!
    win_w = 1240.0 / zoom
    win_h = 2204.444 / zoom
    cx = (UPS_W / 2.0) + dx
    cy = (UPS_H / 2.0) + dy
    x0 = cx - win_w / 2.0
    y0 = cy - win_h / 2.0

    # Affine matrix mapping output (u, v) in [0..W, 0..H] -> source (x, y)
    # cv2.warpAffine with WARP_INVERSE_MAP takes M: dst -> src!
    sx = win_w / float(W)
    sy = win_h / float(H)
    M = np.array([[sx, 0.0, x0], [0.0, sy, y0]], dtype=np.float32)
    out = cv2.warpAffine(
        img, M, (W, H),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    return out

# 5. Measured stems: music baseline 2 LU below speech; automatically duck
# the music when the narrator talks, then release smoothly, with 3s fade-out.
from pilot_engine.audio_balance import mix_speech_and_music
print("Mixing measured speech + automatic music ducking...")
master_audio_path = "/home/user/assets/audio/master_mix.wav"
mix_speech_and_music(
    scenes_meta, "/home/user/assets/audio/ambient_science_bgm.wav",
    TOTAL_DUR, master_audio_path,
)
print("Master audio mixed successfully:", master_audio_path)

# 6. Stream all 60fps 1080x1920 frames directly into FFmpeg H.264 encoder + mux master audio!
output_mp4 = "/home/user/bilgi_dozu_suda_parmaklar_neden_burusur_shorts.mp4"
ffmpeg_cmd = [
    "ffmpeg", "-y",
    "-f", "rawvideo",
    "-vcodec", "rawvideo",
    "-pix_fmt", "bgr24",
    "-s", f"{W}x{H}",
    "-r", str(FPS),
    "-i", "-",
    "-i", master_audio_path,
    "-c:v", "libx264",
    "-preset", "fast",
    "-crf", "18",
    "-profile:v", "high",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "192k",
    "-movflags", "+faststart",
    output_mp4,
]

print(f"Rendering {TOTAL_FRAMES} frames at 1080x1920 @ 60fps -> {output_mp4} ...")
t_render = time.time()
log_f = open("/tmp/ffmpeg_render.log", "w")
proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=log_f)

half_cd = CROSS_DISSOLVE / 2.0  # 0.25s either side of scene boundary

for f_idx in range(TOTAL_FRAMES):
    t = f_idx / float(FPS)

    # Determine active scene and whether we are inside a 0.5s Cross Dissolve window
    active_idx = 5
    for idx, sm in enumerate(scenes_meta):
        if t < sm["scene_end"] or idx == 5:
            active_idx = idx
            break

    sm_cur = scenes_meta[active_idx]
    # Local progress for Ken Burns (include 0.25s pre/post overlap smoothly)
    vis_start = sm_cur["scene_start"] - (half_cd if active_idx > 0 else 0.0)
    vis_end = sm_cur["scene_end"] + (half_cd if active_idx < 5 else 0.0)
    prog_cur = (t - vis_start) / max(0.1, vis_end - vis_start)
    frame = render_ken_burns(active_idx, prog_cur)

    # Check if cross-dissolving into next scene [scene_end - 0.25, scene_end + 0.25]
    # Note: if t is in [sm_cur.scene_end - half_cd, sm_cur.scene_end], blend with active_idx + 1
    if active_idx < 5 and t >= (sm_cur["scene_end"] - half_cd):
        alpha_cd = (t - (sm_cur["scene_end"] - half_cd)) / CROSS_DISSOLVE  # 0.0 -> 0.5
        sm_nxt = scenes_meta[active_idx + 1]
        n_start = sm_nxt["scene_start"] - half_cd
        n_end = sm_nxt["scene_end"] + (half_cd if (active_idx + 1) < 5 else 0.0)
        frame_nxt = render_ken_burns(active_idx + 1, (t - n_start) / max(0.1, n_end - n_start))
        frame = cv2.addWeighted(frame, 1.0 - alpha_cd, frame_nxt, alpha_cd, 0.0)
    elif active_idx > 0 and t < (sm_cur["scene_start"] + half_cd):
        alpha_cd = (t - (sm_cur["scene_start"] - half_cd)) / CROSS_DISSOLVE  # 0.5 -> 1.0
        sm_prv = scenes_meta[active_idx - 1]
        p_start = sm_prv["scene_start"] - (half_cd if (active_idx - 1) > 0 else 0.0)
        p_end = sm_prv["scene_end"] + half_cd
        frame_prv = render_ken_burns(active_idx - 1, (t - p_start) / max(0.1, p_end - p_start))
        frame = cv2.addWeighted(frame_prv, 1.0 - alpha_cd, frame, alpha_cd, 0.0)

    # Apply top & bottom legibility scrim (only on top 460 and bottom 320 rows for speed!)
    frame[:460] = (frame[:460].astype(np.float32) * scrim[:460]).astype(np.uint8)
    frame[H - 320 :] = (frame[H - 320 :].astype(np.float32) * scrim[H - 320 :]).astype(np.uint8)

    # Top Progress Bar (y=58..64, x=72..1008) — signature @bilgidozuofficial bar
    bar_x0, bar_x1 = 72, 1008
    frame[58:64, bar_x0:bar_x1] = (frame[58:64, bar_x0:bar_x1] * 0.45 + np.array([75, 85, 85]) * 0.55).astype(np.uint8)
    fill_x = bar_x0 + int((bar_x1 - bar_x0) * (f_idx / max(1, TOTAL_FRAMES - 1)))
    if fill_x > bar_x0:
        frame[58:64, bar_x0:fill_x] = np.array([46, 255, 220], dtype=np.uint8)  # BGR for #DCFF2E

    # Static Top Brand Pill (y=74..154) & Bottom Footer (y=1740..1890)
    blend_band_inplace(frame, 74, top_brand_bgra, 1.0)
    blend_band_inplace(frame, 1740, bot_brand_bgra, 1.0)

    # Upper 1/3 Scene Title Overlay (y=155..455) with smooth 0.25s fade-in / fade-out
    dt_in = t - sm_cur["scene_start"]
    dt_out = sm_cur["scene_end"] - t
    title_op = min(1.0, max(0.0, dt_in / 0.25), max(0.0, dt_out / 0.25))
    blend_band_inplace(frame, 155, upper_titles_bgra[active_idx], title_op)

    # Active Dynamic Subtitle Band (y=1240..1480)
    for st0, st1, sband in sub_timeline:
        if st0 <= t < st1:
            sub_op = min(1.0, (t - st0) / 0.12, (st1 - t) / 0.12)
            blend_band_inplace(frame, 1240, sband, max(0.0, sub_op))
            break

    # Gentle 0.35s fade-in from black at t=0 and 0.45s fade-out to black at very end
    if t < 0.35:
        frame = (frame.astype(np.float32) * (t / 0.35)).astype(np.uint8)
    elif t > (TOTAL_DUR - 0.45):
        rem = max(0.0, (TOTAL_DUR - t) / 0.45)
        frame = (frame.astype(np.float32) * rem).astype(np.uint8)

    proc.stdin.write(frame.tobytes())

proc.stdin.close()
ret = proc.wait()
log_f.close()
if ret != 0:
    print("FFmpeg error:", open("/tmp/ffmpeg_render.log").read()[-1500:])
    raise SystemExit(ret)

print(f"DONE in {time.time() - t_render:.1f}s! Saved {output_mp4} ({os.path.getsize(output_mp4)/(1024*1024):.2f} MB)")
