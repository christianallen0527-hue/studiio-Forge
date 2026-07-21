"""Client-facing brand placeholders — sponsor spot + ending card.

These are demo fillers so a review cut shows where real sponsor media and an
outro will land. Replace with client assets via ``sponsor.video`` / ``outro.video``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from . import ffmpeg, textgen


def _card_png(
    out: Path,
    width: int,
    height: int,
    *,
    kicker: str,
    title: str,
    subtitle: str,
    bg: tuple[int, int, int],
    accent: tuple[int, int, int],
) -> Path:
    img = Image.new("RGB", (width, height), bg)
    d = ImageDraw.Draw(img)
    # Soft vignette bars
    bar = max(8, height // 90)
    d.rectangle([0, 0, width, bar * 6], fill=tuple(max(0, c - 12) for c in bg))
    d.rectangle([0, height - bar * 6, width, height],
                fill=tuple(max(0, c - 12) for c in bg))

    kf = textgen._font(int(height * 0.028), bold=True)
    tf = textgen._font(int(height * 0.08), bold=True)
    sf = textgen._font(int(height * 0.032))

    kb = d.textbbox((0, 0), kicker, font=kf)
    d.text(((width - (kb[2] - kb[0])) / 2, height * 0.32), kicker,
           font=kf, fill=accent)

    tb = d.textbbox((0, 0), title, font=tf)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    ty = height * 0.40
    d.text(((width - tw) / 2, ty), title, font=tf, fill=(245, 245, 245))

    # Accent rule
    rule_y = ty + th + int(height * 0.03)
    d.rectangle([width / 2 - 48, rule_y, width / 2 + 48, rule_y + 3], fill=accent)

    if subtitle:
        sb = d.textbbox((0, 0), subtitle, font=sf)
        sw = sb[2] - sb[0]
        d.text(((width - sw) / 2, rule_y + int(height * 0.04)), subtitle,
               font=sf, fill=(180, 180, 180))

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def _png_to_clip(
    png: Path,
    out_path: Path,
    *,
    width: int,
    height: int,
    fps: int,
    duration: float,
    fade: float = 0.7,
) -> Path:
    out_path = Path(out_path)
    fade = min(max(0.0, fade), max(0.0, duration / 2.0))
    fout = max(0.0, duration - fade)
    if fade >= 0.02:
        vf = (f"fps={fps},format=yuv420p,"
              f"fade=t=in:st=0:d={fade:.3f},fade=t=out:st={fout:.3f}:d={fade:.3f}")
    else:
        vf = f"fps={fps},format=yuv420p"
    ffmpeg.run([
        "ffmpeg", "-y", "-v", "error",
        "-loop", "1", "-i", str(png),
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(out_path),
    ])
    return out_path


def make_sponsor_placeholder(
    out_path: str | Path,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    duration: float = 8.0,
    sponsor_name: str = "Sample Sponsor",
) -> Path:
    """Fake mid-roll / mid-show advert slot for client review cuts."""
    out_path = Path(out_path)
    png = out_path.with_suffix(".png")
    _card_png(
        png, width, height,
        kicker="SPONSOR SPOT",
        title=sponsor_name,
        subtitle="Placeholder ad · replace with client creative",
        bg=(18, 22, 28),
        accent=(212, 168, 75),
    )
    return _png_to_clip(png, out_path, width=width, height=height,
                        fps=fps, duration=duration, fade=0.8)


def make_outro_placeholder(
    out_path: str | Path,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    duration: float = 5.0,
    show_name: str = "AUTOEDITING FORGE",
) -> Path:
    """End card so the episode closes instead of hard-cutting out."""
    out_path = Path(out_path)
    png = out_path.with_suffix(".png")
    _card_png(
        png, width, height,
        kicker="END OF EPISODE",
        title="Thanks for watching",
        subtitle=show_name,
        bg=(12, 12, 14),
        accent=(200, 170, 90),
    )
    return _png_to_clip(png, out_path, width=width, height=height,
                        fps=fps, duration=duration, fade=0.9)
