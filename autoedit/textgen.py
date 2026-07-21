"""Text rendering with Pillow → PNG (this ffmpeg lacks drawtext/subtitles).

Produces full-frame title cards and transparent caption strips that ffmpeg then
composites with the `overlay` / `fade` filters.
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_REG = ["/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf"]
_BOLD = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/System/Library/Fonts/SFNSDisplay.ttf"]


def _font(size: int, bold: bool = False):
    for p in (_BOLD if bold else _REG):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_w: int, max_lines: int = 3) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:max_lines]


def title_card_png(title: str, subtitle: str, w: int, h: int,
                   out: str | Path, bg=(10, 10, 10)) -> Path:
    out = Path(out)
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    tf = _font(int(h * 0.09), bold=True)
    bb = d.textbbox((0, 0), title, font=tf)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    ty = h / 2 - th - int(h * 0.015)
    d.text(((w - tw) / 2, ty), title, font=tf, fill=(245, 245, 245))
    # subtle accent rule under the title
    d.rectangle([w / 2 - 40, h / 2 + int(h * 0.005), w / 2 + 40,
                 h / 2 + int(h * 0.005) + 3], fill=(200, 170, 90))
    if subtitle:
        sf = _font(int(h * 0.036))
        sb = d.textbbox((0, 0), subtitle, font=sf)
        sw = sb[2] - sb[0]
        d.text(((w - sw) / 2, h / 2 + int(h * 0.03)), subtitle,
               font=sf, fill=(176, 176, 176))
    img.save(out)
    return out


def caption_png(text: str, w: int, out: str | Path,
                fontsize: int = 54, pad: int = 20) -> tuple[Path, int]:
    """Transparent caption strip (white text, heavy outline), width w."""
    out = Path(out)
    probe = ImageDraw.Draw(Image.new("RGBA", (w, 10)))
    font = _font(fontsize, bold=True)
    lines = _wrap(probe, text, font, w - 4 * pad)
    line_h = fontsize + 10
    total_h = line_h * len(lines) + 2 * pad
    img = Image.new("RGBA", (w, total_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = pad
    for ln in lines:
        lw = d.textlength(ln, font=font)
        d.text(((w - lw) / 2, y), ln, font=font, fill=(255, 255, 255),
               stroke_width=5, stroke_fill=(0, 0, 0))
        y += line_h
    img.save(out)
    return out, total_h
