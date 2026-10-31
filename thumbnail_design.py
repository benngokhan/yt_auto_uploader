"""Create a branded fallback cover from the *newly published video's* own art.

No image-generation API or external service is called. The original scene is
cropped to avoid the normal title/subtitle bands and a Turkish headline is added.
If extraction, Pillow, or fonts fail, callers must simply skip the cover step.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

FONT = Path(__file__).resolve().parent / 'assets' / 'Anton-Regular.ttf'


def tr_upper(text: str) -> str:
    return text.translate(str.maketrans({'i':'İ','ı':'I'})).upper()


def headline_lines(title: str, max_width: int = 24, max_lines: int = 3) -> list[str]:
    """Remove tags/emoji, keep whole words, and avoid Turkish I/İ case errors."""
    text = re.sub(r'https?://\S+|#\S+', ' ', str(title or ''))
    keep = []
    for ch in text:
        category = unicodedata.category(ch)
        if category.startswith(('L','N')) or ch in " ?!:'’.-":
            keep.append(ch)
        else:
            keep.append(' ')
    text = re.sub(r'\s+', ' ', ''.join(keep)).strip()
    if not text:
        raise ValueError('Kapak başlığı boş')
    words = tr_upper(text).split()
    lines = []
    remaining = False
    for i, word in enumerate(words):
        if not lines or len(lines[-1]) + 1 + len(word) > max_width:
            if len(lines) == max_lines:
                remaining = True
                break
            lines.append(word)
        else:
            lines[-1] += ' ' + word
    if remaining:
        lines[-1] = lines[-1].rstrip(' .,!?:;') + '…'
    return lines


def ffmpeg_binary() -> str:
    # imageio-ffmpeg is already installed by the existing workflow requirements.
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        p = shutil.which('ffmpeg')
        if p:
            return p
        raise RuntimeError('FFmpeg bulunamadı')


def render_from_frame(frame_path: Path, destination: Path, title: str, is_short: bool) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter, ImageEnhance

    if not FONT.is_file():
        raise FileNotFoundError('Kapak yazı tipi bulunamadı')
    width, height = (1080, 1920) if is_short else (1280, 720)
    with Image.open(frame_path) as image:
        frame = ImageOps.exif_transpose(image).convert('RGB')
    fw, fh = frame.size
    if fw < 100 or fh < 100:
        raise ValueError('Video karesi çok küçük')
    # Skip persistent top headings and lower subtitle/source overlays of the
    # channel's template. This is a visual approximation, not face detection.
    crop = frame.crop((0, round(fh * .22), fw, round(fh * .64)))
    if crop.height < 30:
        raise ValueError('Video karesi kırpılamadı')
    poster = ImageEnhance.Brightness(
        ImageOps.fit(frame, (width,height), method=Image.Resampling.LANCZOS)
        .filter(ImageFilter.GaussianBlur(28))
    ).enhance(.19).convert('RGBA')
    # Deep navy glaze keeps the upper zone close to the approved visual style.
    navy = Image.new('RGBA',(width,height),(0,13,29,120))
    poster = Image.alpha_composite(poster,navy)
    top = int(height * (.28 if is_short else .30))
    art = ImageOps.fit(crop,(width,height-top),method=Image.Resampling.LANCZOS).convert('RGBA')
    # Feather the upper edge so the illustration flows into the navy headline area.
    fade = min(90 if is_short else 34, art.height)
    alpha = Image.new('L', art.size, 255)
    alpha_draw = ImageDraw.Draw(alpha)
    for y in range(fade):
        alpha_draw.line((0,y,width,y),fill=int(255*y/max(1,fade-1)))
    art.putalpha(alpha)
    poster.alpha_composite(art,(0,top))

    draw = ImageDraw.Draw(poster)
    lines = headline_lines(title,24 if is_short else 30)
    max_font = 164 if is_short else 88
    max_box_height = top - (36 if is_short else 18)
    padding = 14 if is_short else 7
    margin_top = 35 if is_short else 15
    for size in range(max_font,32,-1):
        font = ImageFont.truetype(str(FONT),size)
        boxes = [draw.textbbox((0,0),s,font=font) for s in lines]
        text_height = sum(b[3]-b[1] for b in boxes) + padding*(len(boxes)-1)
        if max(b[2]-b[0] for b in boxes) <= width*.92 and text_height <= max_box_height-margin_top:
            break
    y = margin_top
    for i,(line,b) in enumerate(zip(lines,boxes)):
        x = int((width-(b[2]-b[0]))/2-b[0]); yy = y-b[1]
        shadow = max(3,size//22)
        draw.text((x+3,yy+5),line,font=font,fill=(0,0,0,255),stroke_width=shadow,stroke_fill=(0,0,0,255))
        draw.text((x,yy),line,font=font,fill=(255,255,255,255) if i==0 else (255,204,18,255),stroke_width=1,stroke_fill=(0,0,0,255))
        y += b[3]-b[1]+padding
    poster.convert('RGB').save(destination,'JPEG',quality=88,optimize=True,subsampling=0)
    if destination.stat().st_size > 2_000_000:
        # Stay compatible with more restrictive custom-thumbnail clients.
        with Image.open(destination) as image:
            image.convert('RGB').save(destination,'JPEG',quality=78,optimize=True)


def make_video_cover(video_path: Path, destination: Path, title: str, is_short: bool) -> None:
    """Extract one representative scene with a bounded FFmpeg subprocess."""
    video_path, destination = Path(video_path), Path(destination)
    if not video_path.is_file():
        raise FileNotFoundError('Video dosyası bulunamadı')
    with tempfile.TemporaryDirectory(prefix='bd-thumb-') as temp:
        frame = Path(temp)/'frame.jpg'
        command = [ffmpeg_binary(), '-hide_banner', '-loglevel', 'error', '-ss', '1.0',
                   '-i', str(video_path), '-frames:v', '1', '-an', '-q:v', '2', '-y', str(frame)]
        subprocess.run(command,check=True,timeout=30,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        if not frame.is_file():
            raise RuntimeError('Videodan kare alınamadı')
        render_from_frame(frame,destination,title,is_short)
