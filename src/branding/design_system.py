"""Shared editorial design system for canonical source-backed branded content."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageStat


@dataclass(frozen=True)
class DesignTokens:
    canvas_width: int = 1080
    canvas_height: int = 1350
    margin_x: int = 54
    margin_top: int = 54
    margin_bottom: int = 54
    headline_max_width: int = 610
    headline_font_size: int = 64
    headline_line_spacing: int = 8
    supporting_font_size: int = 25
    brand_card_padding: int = 18
    brand_card_radius: int = 14
    footer_height: int = 96
    footer_gap: int = 24
    broker_logo_max_width: int = 130
    project_identity_max_width: int = 260
    developer_identity_max_width: int = 165
    burgundy_accent_width: int = 8
    panel_height: int = 390
    image_corner_radius: int = 20


TOKENS = DesignTokens()
DOMUS_BURGUNDY = (120, 24, 16, 255)
INK = (17, 17, 17, 255)
MUTED = (82, 82, 82, 255)
PAPER = (255, 255, 255, 255)
DIVIDER = (221, 221, 221, 255)

LAYOUT_FAMILIES = {
    "project_overview": "PROJECT_OVERVIEW_EDITORIAL",
    "villas": "PROPERTY_SHOWCASE",
    "property": "PROPERTY_SHOWCASE",
    "architecture": "ARCHITECTURE_SHOWCASE",
    "interiors": "INTERIOR_SHOWCASE",
    "interior": "INTERIOR_SHOWCASE",
    "amenities": "AMENITY_SHOWCASE",
    "amenity": "AMENITY_SHOWCASE",
    "location": "LOCATION_EDITORIAL",
    "features": "FEATURE_EDITORIAL",
    "unit_information": "TECHNICAL_INFORMATION",
    "investment_facts": "TECHNICAL_INFORMATION",
}


def layout_family(content_topic: str | None) -> str:
    return LAYOUT_FAMILIES.get(str(content_topic or "").casefold(), "FEATURE_EDITORIAL")


def font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        try:
            return ImageFont.truetype(str(path) if path.is_file() else name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.ImageFont, width: int, lines: int = 2) -> list[str]:
    words = str(text).split()
    result: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), candidate, font=face)[2] > width:
            result.append(current)
            current = word
        else:
            current = candidate
    if current:
        result.append(current)
    if len(result) > lines:
        result = result[:lines]
        result[-1] = result[-1].rstrip(".,") + "…"
    return result or [str(text)]


def rounded_bottom_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    draw.rectangle((0, 0, size[0], size[1] - radius), fill=255)
    return mask


def safe_image_frame(image: Image.Image, size: tuple[int, int]) -> tuple[Image.Image, list[int], float, bool]:
    """Fill an editorial image frame without stretching or destructive wide-image crops."""
    source_ratio = image.width / image.height
    target_ratio = size[0] / size[1]
    crop_fraction = abs(1 - target_ratio / source_ratio) if source_ratio > target_ratio else abs(1 - source_ratio / target_ratio)
    if crop_fraction <= .22:
        framed = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(.5, .5))
        return framed, [0, 0, size[0], size[1]], crop_fraction, False
    contained = ImageOps.contain(image, size, method=Image.Resampling.LANCZOS)
    blurred = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(28))
    veil = Image.new("RGBA", size, (255, 255, 255, 58))
    framed = Image.alpha_composite(blurred.convert("RGBA"), veil).convert("RGB")
    x, y = (size[0] - contained.width) // 2, (size[1] - contained.height) // 2
    framed.paste(contained, (x, y))
    return framed, [x, y, x + contained.width, y + contained.height], 0.0, True


def paste_logo(canvas: Image.Image, logo_path: Path, xy: tuple[int, int], max_width: int) -> tuple[list[int], float]:
    with Image.open(logo_path) as raw:
        logo = ImageOps.exif_transpose(raw).convert("RGBA")
    ratio = logo.width / logo.height
    width = max_width
    height = round(width / ratio)
    logo = logo.resize((width, height), Image.Resampling.LANCZOS)
    canvas.alpha_composite(logo, xy)
    return [xy[0], xy[1], xy[0] + width, xy[1] + height], ratio


def paste_project_identity(
    canvas: Image.Image,
    project_brand: dict[str, Any],
    box: tuple[int, int, int, int],
    identity_treatment: dict[str, Any] | None,
) -> dict[str, Any]:
    if not project_brand.get("available"):
        return {"project_identity_box": None, "developer_identity_box": None, "project_identity_aspect_ratio": None}
    x1, y1, x2, y2 = box
    draw = ImageDraw.Draw(canvas)
    fill = tuple((identity_treatment or {}).get("rgba", (21, 21, 21, 255)))
    draw.rounded_rectangle(box, radius=TOKENS.brand_card_radius, fill=fill)
    with Image.open(project_brand["path"]) as raw:
        mark = ImageOps.exif_transpose(raw).convert("RGBA")
    ratio = mark.width / mark.height
    max_w = min(TOKENS.project_identity_max_width, x2 - x1 - 2 * TOKENS.brand_card_padding)
    max_h = 58
    mark.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    mark_x = x1 + (x2 - x1 - mark.width) // 2
    mark_y = y1 + TOKENS.brand_card_padding
    canvas.alpha_composite(mark, (mark_x, mark_y))
    developer_box = None
    developer_path = project_brand.get("developer_wordmark_path")
    if developer_path:
        with Image.open(developer_path) as raw:
            developer = ImageOps.exif_transpose(raw).convert("RGBA")
        developer.thumbnail((TOKENS.developer_identity_max_width, 25), Image.Resampling.LANCZOS)
        dev_x = x1 + (x2 - x1 - developer.width) // 2
        dev_y = min(y2 - TOKENS.brand_card_padding - developer.height, mark_y + mark.height + 10)
        canvas.alpha_composite(developer, (dev_x, dev_y))
        developer_box = [dev_x, dev_y, dev_x + developer.width, dev_y + developer.height]
    return {
        "project_identity_box": [mark_x, mark_y, mark_x + mark.width, mark_y + mark.height],
        "developer_identity_box": developer_box,
        "project_identity_aspect_ratio": round(ratio, 6),
    }


def draw_footer(draw: ImageDraw.ImageDraw, website: str | None, top: int) -> list[int]:
    draw.line((TOKENS.margin_x, top, TOKENS.canvas_width - TOKENS.margin_x, top), fill=DIVIDER, width=2)
    center_y = top + TOKENS.footer_height // 2
    icon_x = TOKENS.canvas_width - TOKENS.margin_x - 265
    draw.ellipse((icon_x, center_y - 17, icon_x + 34, center_y + 17), fill=DOMUS_BURGUNDY)
    draw.ellipse((icon_x + 9, center_y - 8, icon_x + 25, center_y + 8), outline=PAPER, width=2)
    draw.line((icon_x + 11, center_y, icon_x + 23, center_y), fill=PAPER, width=2)
    if website:
        draw.text((icon_x + 48, center_y - 15), str(website), font=font(24), fill=INK)
    return [TOKENS.margin_x, top, TOKENS.canvas_width - TOKENS.margin_x, top + TOKENS.footer_height]


def render_showcase(
    source: Path,
    logo_path: Path,
    project_name: str,
    project_brand: dict[str, Any],
    *,
    content_topic: str | None,
    title: str | None,
    website: str | None,
    identity_treatment: dict[str, Any] | None,
) -> tuple[Image.Image, dict[str, Any]]:
    family = layout_family(content_topic)
    with Image.open(source) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
    source_ratio = image.width / image.height
    panel_top = TOKENS.canvas_height - TOKENS.panel_height
    framed, inner_box, crop_fraction, full_source = safe_image_frame(image, (TOKENS.canvas_width, panel_top))
    canvas = Image.new("RGBA", (TOKENS.canvas_width, TOKENS.canvas_height), PAPER)
    canvas.paste(framed.convert("RGBA"), (0, 0), rounded_bottom_mask(framed.size, TOKENS.image_corner_radius))
    draw = ImageDraw.Draw(canvas)
    accent_x = TOKENS.margin_x
    draw.rectangle((accent_x, panel_top + 28, accent_x + TOKENS.burgundy_accent_width, TOKENS.canvas_height - 28), fill=DOMUS_BURGUNDY)
    logo_xy = (TOKENS.margin_x + 28, panel_top + 34)
    logo_box, logo_ratio = paste_logo(canvas, logo_path, logo_xy, TOKENS.broker_logo_max_width)
    headline_x = logo_box[2] + 36
    kicker = str(content_topic or "Property").replace("_", " ").upper()
    draw.text((headline_x, panel_top + 38), kicker, font=font(17, bold=True), fill=DOMUS_BURGUNDY)
    headline = str(title or project_name).strip()
    headline_face = font(TOKENS.headline_font_size, bold=True)
    lines = wrap_text(draw, headline, headline_face, TOKENS.headline_max_width, 2)
    y = panel_top + 68
    for line in lines:
        draw.text((headline_x, y), line, font=headline_face, fill=INK)
        y += TOKENS.headline_font_size + TOKENS.headline_line_spacing
    identity_box = (TOKENS.canvas_width - TOKENS.margin_x - 286, panel_top + 30, TOKENS.canvas_width - TOKENS.margin_x, panel_top + 145)
    identity = paste_project_identity(canvas, project_brand, identity_box, identity_treatment)
    if not project_brand.get("available"):
        draw.rounded_rectangle(identity_box, radius=TOKENS.brand_card_radius, outline=DIVIDER, width=2)
        fallback = wrap_text(draw, project_name, font(24, bold=True), identity_box[2] - identity_box[0] - 32, 2)
        draw.multiline_text((identity_box[0] + 16, identity_box[1] + 30), "\n".join(fallback), font=font(24, bold=True), fill=INK, spacing=5)
    cta_y = TOKENS.canvas_height - TOKENS.footer_height - 72
    cta_box = [headline_x, cta_y, headline_x + 205, cta_y + 50]
    draw.rounded_rectangle(cta_box, radius=4, fill=DOMUS_BURGUNDY)
    draw.text(((cta_box[0] + cta_box[2]) // 2, (cta_box[1] + cta_box[3]) // 2), "Discover More", font=font(22), fill=PAPER, anchor="mm")
    footer_box = draw_footer(draw, website, TOKENS.canvas_height - TOKENS.footer_height)
    source_box = [inner_box[0], inner_box[1], inner_box[2], inner_box[3]]
    return canvas.convert("RGB"), {
        "layout_strategy": family,
        "layout_family": family,
        "logo_box": logo_box,
        "logo_aspect_ratio": round(logo_ratio, 6),
        "panel_box": [0, panel_top, TOKENS.canvas_width, TOKENS.canvas_height],
        "footer_box": footer_box,
        "cta_box": cta_box,
        "supporting_font_size": TOKENS.supporting_font_size,
        "project_name_rendering": "wordmark" if project_brand.get("available") else "generic_fallback",
        **identity,
        "project_identity_rendering": (identity_treatment or {}).get("manifest"),
        "source_render_box": source_box,
        "source_aspect_ratio": round(source_ratio, 6),
        "rendered_source_aspect_ratio": round(source_ratio, 6),
        "source_crop_fraction": round(crop_fraction, 4),
        "full_source_visible": full_source,
        "website_rendered": bool(website),
        "design_tokens": TOKENS.__dict__,
    }
