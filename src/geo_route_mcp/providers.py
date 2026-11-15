"""Map backgrounds. OSM fetches only the current viewport; Google is preview-only."""

import json
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from io import BytesIO
from math import asinh, floor, log2, pi, radians, tan
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from .models import Route
from .render import RenderOptions, _unwrap, draw_endpoints, draw_metadata

OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_ATTRIBUTION = "© OpenStreetMap contributors · ODbL"
ESRI_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
ESRI_ATTRIBUTION = "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community"
MERCATOR_LIMIT = 85.05112878


class ProviderInfo(BaseModel):
    id: str = Field(description="Provider identifier; use image_export=true IDs in render_route.provider.")
    available: bool = Field(description="Supported for use locally; not a live connectivity check.")
    image_export: bool = Field(description="Whether this provider may produce PNG/JPEG via render_route.")
    network: bool = Field(description="Whether rendering with this provider needs network access.")
    configured: bool = Field(default=True, description="Whether required local configuration is present.")
    attribution: str | None = Field(default=None, description="Credit that must remain visible on exported maps.")
    note: str | None = Field(default=None, description="Provider usage limits or conditions.")


def list_providers() -> list[ProviderInfo]:
    return [
        ProviderInfo(id="none", available=True, image_export=True, network=False),
        ProviderInfo(id="openstreetmap", available=True, image_export=True, network=True,
                     attribution=OSM_ATTRIBUTION,
                     note="Viewport-only tile requests; HTTP cache and visible attribution required."),
        ProviderInfo(id="esri_satellite", available=True, image_export=True, network=True,
                     attribution=ESRI_ATTRIBUTION,
                     note="Personal static map use with Esri and data-source attribution."),
        ProviderInfo(id="google_satellite", available=False,
                     configured=bool(os.getenv("GOOGLE_MAPS_API_KEY")) and
                     os.getenv("GOOGLE_MAPS_ENABLED", "false").lower() == "true",
                     image_export=False, network=True,
                     note="API credentials can be configured; image export is disabled by Google content terms."),
    ]


def _world_point(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    if abs(lat) > MERCATOR_LIMIT:
        raise ValueError("OpenStreetMap tiles cannot render latitudes beyond Web Mercator limits")
    size = 256 * 2**zoom
    lat_rad = radians(lat)
    return ((lon + 180) / 360 * size,
            (1 - asinh(tan(lat_rad)) / pi) / 2 * size)


class OSMTileProvider:
    """OSMF raster tiles with a persistent HTTP-aware cache."""

    def __init__(self, cache_dir: Path | None = None, *, user_agent: str = "geo-route-mcp/0.1 (+https://github.com/openstreetmap)"):
        self.cache_dir = cache_dir or Path(os.getenv("GEO_ROUTE_TILE_CACHE_DIR", Path.home() / ".cache/geo-route-mcp/tiles"))
        self.user_agent = user_agent

    def tile(self, zoom: int, x: int, y: int) -> Image.Image:
        tile_path = self.cache_dir / str(zoom) / str(x) / f"{y}.png"
        meta_path = tile_path.with_suffix(".json")
        metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        now = datetime.now(timezone.utc)
        if tile_path.exists() and metadata.get("expires"):
            if datetime.fromisoformat(metadata["expires"]) > now:
                return Image.open(tile_path).convert("RGB")
        headers = {"User-Agent": self.user_agent}
        if tile_path.exists():
            if metadata.get("etag"):
                headers["If-None-Match"] = metadata["etag"]
            if metadata.get("last_modified"):
                headers["If-Modified-Since"] = metadata["last_modified"]
        request = Request(OSM_URL.format(z=zoom, x=x, y=y), headers=headers)
        try:
            response = urlopen(request, timeout=20)
        except HTTPError as error:
            if error.code != 304 or not tile_path.exists():
                raise
            # A validated cached tile remains available for at least seven days.
            metadata["expires"] = (now + timedelta(days=7)).isoformat()
            meta_path.write_text(json.dumps(metadata))
            return Image.open(tile_path).convert("RGB")
        with response:
            data = response.read()
            tile = Image.open(BytesIO(data)).convert("RGB")
            if tile.size != (256, 256):
                raise ValueError("unexpected OSM tile size")
            cache_control = response.headers.get("Cache-Control", "")
            max_age = next((int(part.split("=", 1)[1]) for part in cache_control.split(",")
                            if part.strip().startswith("max-age=") and part.strip().split("=", 1)[1].isdigit()), None)
            expires = now + timedelta(seconds=max_age) if max_age is not None else now + timedelta(days=7)
            if max_age is None and response.headers.get("Expires"):
                try:
                    expires = parsedate_to_datetime(response.headers["Expires"])
                except (TypeError, ValueError):
                    pass
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            tile_path.write_bytes(data)
            meta_path.write_text(json.dumps({
                "expires": expires.isoformat(),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
            }))
            return tile

    def render(self, route: Route, options: RenderOptions | None = None) -> Image.Image:
        options = options or RenderOptions()
        unwrapped = _unwrap(route)
        latitudes = [lat for segment in unwrapped for _, lat in segment]
        if any(abs(lat) > MERCATOR_LIMIT for lat in latitudes):
            raise ValueError("route lies outside Web Mercator tile coverage")
        padding = max(16, round(min(options.width, options.height) * options.padding_fraction))
        usable_w, usable_h = options.width - 2 * padding, options.height - 2 * padding
        if usable_w <= 0 or usable_h <= 0:
            raise ValueError("padding leaves no drawing area")
        base = [[_world_point(lon, lat, 0) for lon, lat in segment] for segment in unwrapped]
        flat = [point for segment in base for point in segment]
        min_x, max_x = min(x for x, _ in flat), max(x for x, _ in flat)
        min_y, max_y = min(y for _, y in flat), max(y for _, y in flat)
        span_x, span_y = max_x - min_x, max_y - min_y
        if span_x == 0 and span_y == 0:
            zoom = 15
        else:
            fit = min(usable_w / span_x if span_x else float("inf"),
                      usable_h / span_y if span_y else float("inf"))
            zoom = max(0, min(19, floor(log2(fit))))
        multiplier = 2**zoom
        center_x = (min_x + max_x) / 2 * multiplier
        center_y = (min_y + max_y) / 2 * multiplier
        left, top = center_x - options.width / 2, center_y - options.height / 2
        first_x, last_x = floor(left / 256), floor((left + options.width - 1) / 256)
        first_y, last_y = floor(top / 256), floor((top + options.height - 1) / 256)
        tile_count = (last_x - first_x + 1) * (last_y - first_y + 1)
        if tile_count > 64:
            raise ValueError("image would request more than 64 tiles")
        image = Image.new("RGB", (options.width, options.height), "white")
        n = 2**zoom
        for x in range(first_x, last_x + 1):
            for y in range(first_y, last_y + 1):
                if 0 <= y < n:
                    tile = self.tile(zoom, x % n, y)
                    image.paste(tile, (round(x * 256 - left), round(y * 256 - top)))
        draw = ImageDraw.Draw(image)
        def pixel(point: tuple[float, float]) -> tuple[float, float]:
            return (point[0] * multiplier - left, point[1] * multiplier - top)
        points = [[pixel(p) for p in segment] for segment in base]
        for segment in points:
            if len(segment) >= 2:
                draw.line(segment, fill=options.line_color, width=options.line_width, joint="curve")
        draw_endpoints(image, points[0][0], points[-1][-1], options)
        if options.show_metadata:
            draw_metadata(image, route)
            draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=max(12, min(18, round(options.width / 70))))
        bounds = draw.textbbox((0, 0), OSM_ATTRIBUTION, font=font)
        text_w, text_h = bounds[2] - bounds[0], bounds[3] - bounds[1]
        if text_w + 8 > options.width:
            raise ValueError("image is too narrow for required OSM attribution")
        x, y = options.width - text_w - 8, options.height - text_h - 8
        draw.rectangle((x - 4, y - 3, options.width, options.height), fill="white")
        draw.text((x, y), OSM_ATTRIBUTION, fill="black", font=font)
        return image


class EsriSatelliteProvider:
    """Render one requested static satellite image using ArcGIS World Imagery."""

    def render(self, route: Route, options: RenderOptions | None = None) -> Image.Image:
        options = options or RenderOptions()
        if options.width > 4096 or options.height > 4096:
            raise ValueError("Esri World Imagery export is limited to 4096 pixels per dimension")
        if not 0 <= options.padding_fraction < 0.5:
            raise ValueError("invalid padding")
        unwrapped = _unwrap(route)
        points = []
        for segment in unwrapped:
            transformed = []
            for lon, lat in segment:
                if abs(lat) > MERCATOR_LIMIT:
                    raise ValueError("satellite map cannot render latitudes beyond Web Mercator limits")
                transformed.append((6378137 * radians(lon),
                                    6378137 * asinh(tan(radians(lat)))))
            points.append(transformed)
        flat = [point for segment in points for point in segment]
        xs, ys = [p[0] for p in flat], [p[1] for p in flat]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        usable = 1 - 2 * options.padding_fraction
        span_x = max((max_x - min_x) / usable, 50)
        span_y = max((max_y - min_y) / usable, 50)
        ratio = options.width / options.height
        if span_x / span_y < ratio:
            span_x = span_y * ratio
        else:
            span_y = span_x / ratio
        cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2
        left, right = cx - span_x / 2, cx + span_x / 2
        bottom, top = cy - span_y / 2, cy + span_y / 2
        query = urlencode({
            "bbox": f"{left},{bottom},{right},{top}", "bboxSR": 3857,
            "imageSR": 3857, "size": f"{options.width},{options.height}",
            "format": "png", "f": "image",
        })
        with urlopen(Request(ESRI_URL + "?" + query,
                             headers={"User-Agent": "geo-route-mcp/0.1"}), timeout=30) as response:
            data = response.read()
        image = Image.open(BytesIO(data)).convert("RGB")
        if image.size != (options.width, options.height):
            raise ValueError("unexpected satellite map image dimensions")
        draw = ImageDraw.Draw(image)

        def pixel(point: tuple[float, float]) -> tuple[float, float]:
            return ((point[0] - left) / span_x * options.width,
                    (top - point[1]) / span_y * options.height)

        pixels = [[pixel(point) for point in segment] for segment in points]
        for segment in pixels:
            if len(segment) >= 2:
                draw.line(segment, fill=options.line_color, width=options.line_width, joint="curve")
        draw_endpoints(image, pixels[0][0], pixels[-1][-1], options)
        if options.show_metadata:
            draw_metadata(image, route)
            draw = ImageDraw.Draw(image)
        credit = f"© 2026 Esri and its licensors · {ESRI_ATTRIBUTION}"
        font = ImageFont.load_default(size=max(10, min(14, round(options.width / 75))))
        lines: list[str] = []
        current = ""
        for word in credit.split():
            candidate = f"{current} {word}".strip()
            if current and draw.textbbox((0, 0), candidate, font=font)[2] > options.width - 16:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
        boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        widths = [box[2] - box[0] for box in boxes]
        heights = [box[3] - box[1] for box in boxes]
        panel_width = max(widths) + 12
        panel_height = sum(heights) + 4 * (len(lines) - 1) + 10
        if panel_width > image.width or panel_height > image.height:
            raise ValueError("image is too small for required Esri attribution")
        x, y = image.width - panel_width, image.height - panel_height
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        credit_draw = ImageDraw.Draw(overlay)
        credit_draw.rectangle((x, y, image.width, image.height), fill=(0, 0, 0, 170))
        line_y = y + 5
        for line, height in zip(lines, heights):
            credit_draw.text((x + 6, line_y), line, fill="white", font=font)
            line_y += height + 4
        return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
