"""Offline route-only raster rendering; no network or map API calls."""

from math import cos, hypot, radians
from typing import Literal

from PIL import Image, ImageColor, ImageDraw, ImageFont
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import Route

PRESETS: dict[str, tuple[int, int]] = {
    "instagram_portrait": (1080, 1350),
    "instagram_square": (1080, 1080),
    "landscape": (1920, 1080),
}


class RenderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(default=1080, ge=64, le=8192)
    height: int = Field(default=1080, ge=64, le=8192)
    padding_fraction: float = Field(default=0.08, ge=0, le=0.4)
    line_color: str = "#FF4F3C"
    line_width: int = Field(default=6, ge=1, le=100)
    start_color: str = "#20bf6b"
    end_color: str = "#eb3b5a"
    background_color: str | None = None
    output_format: Literal["PNG", "JPEG"] = "PNG"
    show_metadata: bool = False

    @classmethod
    def from_preset(cls, name: str, **overrides: object) -> "RenderOptions":
        if name not in PRESETS:
            raise ValueError(f"unknown preset: {name}")
        return cls(width=PRESETS[name][0], height=PRESETS[name][1], **overrides)

    @field_validator("line_color", "start_color", "end_color", "background_color")
    @classmethod
    def valid_color(cls, value: str | None) -> str | None:
        if value is not None:
            ImageColor.getrgb(value)
        return value


def _unwrap(route: Route) -> list[list[tuple[float, float]]]:
    """Keep antimeridian crossings short while preserving each segment boundary."""
    result: list[list[tuple[float, float]]] = []
    previous: float | None = None
    for segment in route.segments:
        output: list[tuple[float, float]] = []
        for point in segment:
            lon = point.longitude
            if previous is not None:
                lon += 360 * round((previous - lon) / 360)
            output.append((lon, point.latitude))
            previous = lon
        result.append(output)
    return result


def render_route(route: Route, options: RenderOptions | None = None) -> Image.Image:
    """Render supplied GPS positions in an equirectangular local projection."""
    options = options or RenderOptions()
    segments = _unwrap(route)
    latitudes = [lat for segment in segments for _, lat in segment]
    longitude_scale = max(cos(radians((min(latitudes) + max(latitudes)) / 2)), 1e-6)
    projected = [[(lon * longitude_scale, -lat) for lon, lat in segment] for segment in segments]
    flat = [point for segment in projected for point in segment]
    min_x, max_x = min(x for x, _ in flat), max(x for x, _ in flat)
    min_y, max_y = min(y for _, y in flat), max(y for _, y in flat)
    marker_radius = max(12, min(22, round(min(options.width, options.height) / 50)),
                        options.line_width + 7)
    padding = max(marker_radius + 5,
                  round(min(options.width, options.height) * options.padding_fraction))
    usable_width = options.width - 2 * padding
    usable_height = options.height - 2 * padding
    if usable_width <= 0 or usable_height <= 0:
        raise ValueError("padding leaves no drawing area")
    span_x, span_y = max_x - min_x, max_y - min_y
    scale = min(usable_width / span_x if span_x else float("inf"),
                usable_height / span_y if span_y else float("inf"))
    if scale == float("inf"):
        scale = 1.0
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    def pixel(point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        return (options.width / 2 + (x - center_x) * scale,
                options.height / 2 + (y - center_y) * scale)

    background = options.background_color or (0, 0, 0, 0)
    image = Image.new("RGBA", (options.width, options.height), background)
    draw = ImageDraw.Draw(image)
    for segment in projected:
        if len(segment) >= 2:
            draw.line([pixel(point) for point in segment], fill=options.line_color,
                      width=options.line_width, joint="curve")

    draw_endpoints(image, pixel(projected[0][0]), pixel(projected[-1][-1]), options)
    if options.show_metadata:
        draw_metadata(image, route)
    if options.output_format == "JPEG":
        # JPEG has no alpha; composite transparent pixels over white.
        base = Image.new("RGB", image.size, "white")
        base.paste(image, mask=image.getchannel("A"))
        return base
    return image


def draw_endpoints(
    image: Image.Image,
    start: tuple[float, float],
    finish: tuple[float, float],
    options: RenderOptions,
) -> None:
    """Draw distinct badges and separate them when a loop's endpoints overlap."""
    draw = ImageDraw.Draw(image)
    radius = max(12, min(22, round(min(image.size) / 50)), options.line_width + 7)

    def clamp(point: tuple[float, float]) -> tuple[float, float]:
        edge = radius + 3
        return (max(edge, min(image.width - edge, point[0])),
                max(edge, min(image.height - edge, point[1])))

    badges = [clamp(start), clamp(finish)]
    if hypot(start[0] - finish[0], start[1] - finish[1]) < 3 * radius:
        mid_x, mid_y = (start[0] + finish[0]) / 2, (start[1] + finish[1]) / 2
        badges = [clamp((mid_x - 2.3 * radius, mid_y - 1.5 * radius)),
                  clamp((mid_x + 2.3 * radius, mid_y - 1.5 * radius))]
        for anchor, badge, color in ((start, badges[0], options.start_color),
                                     (finish, badges[1], options.end_color)):
            draw.line((anchor, badge), fill="white", width=5)
            draw.line((anchor, badge), fill=color, width=2)
            x, y = anchor
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="white")

    for index, (center, color) in enumerate(zip(badges, (options.start_color, options.end_color))):
        x, y = center
        draw.ellipse((x - radius + 2, y - radius + 3, x + radius + 2, y + radius + 3),
                     fill="#1c1c1c")
        draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                     fill=color, outline="white", width=4)
        if index == 0:
            # Play triangle for the start.
            draw.polygon(((x - radius * .22, y - radius * .37),
                          (x - radius * .22, y + radius * .37),
                          (x + radius * .4, y)), fill="white")
        else:
            # Stop square for the finish.
            half = radius * .32
            draw.rectangle((x - half, y - half, x + half, y + half), fill="white")


def draw_metadata(image: Image.Image, route: Route) -> None:
    """Add a compact panel for supplied route metadata."""
    metadata = route.metadata
    lines = []
    if metadata.name:
        lines.append(metadata.name)
    if metadata.date:
        lines.append(metadata.date.strftime("%Y-%m-%d"))
    if metadata.distance_km is not None:
        lines.append(f"{metadata.distance_km:.2f} km")
    if metadata.duration_seconds is not None:
        seconds = round(metadata.duration_seconds)
        lines.append(f"{seconds // 60}:{seconds % 60:02d}")
    if metadata.pace_seconds_per_km is not None:
        seconds = round(metadata.pace_seconds_per_km)
        lines.append(f"{seconds // 60}:{seconds % 60:02d} /km")
    if not lines:
        return
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=max(12, min(22, round(min(image.size) / 55))))
    spacing = 5
    widths, heights = [], []
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        widths.append(box[2] - box[0])
        heights.append(box[3] - box[1])
    panel_width = max(widths) + 20
    panel_height = sum(heights) + spacing * (len(lines) - 1) + 20
    if panel_width > image.width or panel_height > image.height:
        raise ValueError("metadata does not fit image")
    draw.rectangle((0, 0, panel_width, panel_height), fill="white")
    y = 10
    for line, height in zip(lines, heights):
        draw.text((10, y), line, fill="black", font=font)
        y += height + spacing
