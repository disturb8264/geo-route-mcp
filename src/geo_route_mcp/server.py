"""FastMCP stdio and authenticated HTTP server."""

import base64
import hmac
import os
import stat
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.responses import JSONResponse

from .analysis import RouteInspection, inspect
from .exporters import export_geojson, export_gpx, export_kml
from .models import Route
from .parsers import parse_coordinates, parse_geojson, parse_gpx, parse_kml
from .providers import EsriSatelliteProvider, OSMTileProvider, ProviderInfo, list_providers
from .render import PRESETS, RenderOptions, render_route as render_plain

load_dotenv(override=False)
mcp = FastMCP("Geo Route MCP")


class RouteSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["coordinates", "gpx", "kml", "geojson"] = Field(
        description="Input type: coordinates is a numeric array; gpx, kml, and geojson are complete document strings."
    )
    content: str | list[list[float]] = Field(
        description="For coordinates, an array of [first, second] or [first, second, elevation_m] GPS numbers; "
        "for gpx/kml/geojson, the full XML/JSON text. Use only actual source GPS positions."
    )
    coordinate_order: Literal["lat_lon", "lon_lat"] | None = Field(
        default=None,
        description="Required only for coordinates: lat_lon means [latitude, longitude], lon_lat means "
        "[longitude, latitude]. Omit for GPX (lat/lon attributes), KML, and GeoJSON (lon,lat)."
    )

    @model_validator(mode="after")
    def valid_shape(self) -> "RouteSource":
        if self.format == "coordinates":
            if not isinstance(self.content, list) or self.coordinate_order is None:
                raise ValueError("coordinates require an array and explicit coordinate_order")
        elif not isinstance(self.content, str):
            raise ValueError("GPX, KML, and GeoJSON require string content")
        return self

    def route(self) -> Route:
        if self.format == "coordinates":
            return parse_coordinates(self.content, order=self.coordinate_order)
        return {"gpx": parse_gpx, "kml": parse_kml, "geojson": parse_geojson}[self.format](self.content)


class RenderedRoute(BaseModel):
    mime_type: str = Field(description="Image MIME type: image/png or image/jpeg.")
    data_base64: str = Field(description="Base64-encoded image bytes; decode and save/display using mime_type.")
    width: int = Field(description="Actual output image width in pixels.")
    height: int = Field(description="Actual output image height in pixels.")
    provider: str = Field(description="Background provider used for this image.")
    attribution: str | None = Field(
        default=None, description="Map credits; keep the embedded credits visible when sharing a map image."
    )


class ConvertedRoute(BaseModel):
    format: Literal["gpx", "kml", "geojson"] = Field(description="Actual output route format.")
    mime_type: str = Field(description="MIME type for the converted text document.")
    content: str = Field(description="Complete GPX/KML/GeoJSON text; save with the matching file extension.")


RenderSource = Annotated[RouteSource, Field(description=
    "Actual GPS route from coordinates, GPX, KML, or GeoJSON. Check an external MCP's real response "
    "shape before mapping Garmin/Strava/etc. data into this source. No route data means do not render."
)]
RenderProvider = Annotated[Literal["none", "openstreetmap", "esri_satellite"], Field(description=
    "none: transparent route-only background, offline; openstreetmap: online street tiles, cached, "
    "visible OSM credit required; esri_satellite: online Esri imagery for personal static maps, "
    "visible Esri/data-source credit required, max 4096 px per side. Google is not an image provider."
)]
RenderPreset = Annotated[Literal["instagram_portrait", "instagram_square", "landscape"] | None,
                         Field(description="Image size preset: instagram_portrait 1080x1350 (4:5), "
                               "instagram_square 1080x1080 (1:1), landscape 1920x1080 (16:9). "
                               "Explicit width/height override the corresponding preset dimension.")]
RenderWidth = Annotated[int | None, Field(description="Output width in pixels; overrides preset width. "
                                           "Allowed range 64-8192; Esri limit 4096.")]
RenderHeight = Annotated[int | None, Field(description="Output height in pixels; overrides preset height. "
                                            "Allowed range 64-8192; Esri limit 4096.")]
RenderFormat = Annotated[Literal["PNG", "JPEG"], Field(description=
    "Encoded image type. PNG keeps transparency with provider none; JPEG uses a white background."
)]
RenderColor = Annotated[str, Field(description="GPS polyline color accepted by Pillow, e.g. #FF4F3C.")]
RenderLineWidth = Annotated[int, Field(description="GPS polyline thickness in pixels, from 1 to 100.")]
RenderMetadata = Annotated[bool, Field(description="If true, draw available source route name, date, "
                                         "distance, duration, and pace. Missing metadata is not invented; "
                                         "inspect_route returns separately computed measurements.")]


def _render_route_bytes(source: RouteSource, provider: str, preset: str | None,
                        width: int | None, height: int | None, output_format: str,
                        line_color: str, line_width: int, show_metadata: bool
                        ) -> tuple[bytes, int, int, str | None]:
    """Share the existing map rendering path between MCP image and legacy JSON tools."""
    route = source.route()
    preset_width, preset_height = PRESETS[preset] if preset else (1080, 1080)
    options = RenderOptions(width=width or preset_width, height=height or preset_height,
                            output_format=output_format, line_color=line_color, line_width=line_width,
                            show_metadata=show_metadata)
    if provider == "openstreetmap":
        image = OSMTileProvider().render(route, options)
        attribution = "© OpenStreetMap contributors · ODbL"
    elif provider == "esri_satellite":
        image = EsriSatelliteProvider().render(route, options)
        attribution = "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community"
    else:
        image = render_plain(route, options)
        attribution = None
    buffer = BytesIO()
    image.save(buffer, format=output_format)
    return buffer.getvalue(), image.width, image.height, attribution


@mcp.tool(name="render_route")
def render_route_tool(
    source: RenderSource,
    provider: RenderProvider = "none",
    preset: RenderPreset = None,
    width: RenderWidth = None,
    height: RenderHeight = None,
    output_format: RenderFormat = "PNG",
    line_color: RenderColor = "#FF4F3C",
    line_width: RenderLineWidth = 6,
    show_metadata: RenderMetadata = False,
) -> Image:
    """Render actual GPS positions as an MCP image for direct display by the client.

    Use Garmin, Strava, or other source GPS positions only after checking their real
    response format; never infer a missing route. Accept coordinates, GPX, KML, or
    GeoJSON; coordinate arrays require an explicit coordinate_order. The supplied
    point order and segment gaps define the route. Use inspect_route first if bounds
    or distance need validation; use list_map_providers if map availability is unclear.

    Returns MCP ImageContent (image/png by default, image/jpeg if requested), so an
    MCP client can display the content directly without decoding a JSON field. The
    output dimensions follow the preset or explicit width/height. OSM and Esri map
    credits are drawn into the image and must remain visible when sharing it. Clients
    that require the former structured JSON Base64 response should call
    render_route_data with the same arguments.
    """
    data, _, _, _ = _render_route_bytes(source, provider, preset, width, height,
                                        output_format, line_color, line_width, show_metadata)
    return Image(data=data, format=output_format.lower())


@mcp.tool(name="render_route_data")
def render_route_data_tool(
    source: RenderSource,
    provider: RenderProvider = "none",
    preset: RenderPreset = None,
    width: RenderWidth = None,
    height: RenderHeight = None,
    output_format: RenderFormat = "PNG",
    line_color: RenderColor = "#FF4F3C",
    line_width: RenderLineWidth = 6,
    show_metadata: RenderMetadata = False,
) -> RenderedRoute:
    """Legacy JSON Base64 route image response for existing clients.

    Uses the same GPS source, provider, dimensions, and rendering as render_route.
    Returns structured mime_type, data_base64, width, height, provider, and attribution;
    decode data_base64 before saving/displaying. For direct MCP image display, prefer
    render_route. Keep OSM/Esri credits visible when sharing a map image.
    """
    data, actual_width, actual_height, attribution = _render_route_bytes(
        source, provider, preset, width, height, output_format,
        line_color, line_width, show_metadata,
    )
    return RenderedRoute(mime_type="image/png" if output_format == "PNG" else "image/jpeg",
                         data_base64=base64.b64encode(data).decode("ascii"),
                         width=actual_width, height=actual_height, provider=provider,
                         attribution=attribution)


@mcp.tool(name="convert_route")
def convert_route_tool(
    source: Annotated[RouteSource, Field(description=
        "Actual GPS route: numeric coordinates require coordinate_order; GPX uses lat/lon attributes; "
        "KML and GeoJSON coordinates use longitude,latitude order."
    )],
    output_format: Annotated[Literal["gpx", "kml", "geojson"], Field(description=
        "Desired text route format. Use gpx for GPX tools, kml for Google Earth, or geojson for GIS/web tools."
    )],
) -> ConvertedRoute:
    """Convert a supplied GPS route to GPX, KML, or GeoJSON text.

    Use this when another format is needed; inspect_route can check the source first.
    Preserves supplied point order, segment boundaries, and elevation where supported.
    GPX point timestamps survive GPX-to-GPX, but KML/GeoJSON output omits per-point times;
    format-specific extensions, arbitrary properties, and styles may be lost. No route
    coordinates are guessed or added. The result's content is the complete text document;
    save it with the extension and MIME type indicated by format and mime_type.
    """
    route = source.route()
    content = {"gpx": export_gpx, "kml": export_kml, "geojson": export_geojson}[output_format](route)
    mime = {"gpx": "application/gpx+xml", "kml": "application/vnd.google-earth.kml+xml",
            "geojson": "application/geo+json"}[output_format]
    return ConvertedRoute(format=output_format, mime_type=mime, content=content)


@mcp.tool(name="inspect_route")
def inspect_route_tool(source: Annotated[RouteSource, Field(description=
    "Existing GPS coordinates, GPX, KML, or GeoJSON. Numeric coordinates need explicit lat_lon or lon_lat "
    "order; do not infer order from ambiguous values or invent missing points."
)]) -> RouteInspection:
    """Validate and measure a real GPS route before rendering or conversion.

    Returns latitude/longitude bounds, point_count, segment_count, antimeridian crossing,
    and distance_km. Distance is a great-circle sum between consecutive points within
    each segment, with no distance added across gaps. start_time/end_time are the first
    and last supplied point timestamps; duration_seconds is available when their values
    can be compared, and pace_seconds_per_km also needs positive distance. Coordinates
    without timestamps have no duration or pace. Invalid, empty, or out-of-range input
    raises an error instead of returning valid=false; request real GPS data if absent.
    Use render_route for an image or convert_route for another file format afterward.
    """
    return inspect(source.route())


@mcp.tool(name="list_map_providers")
def list_map_providers_tool() -> list[ProviderInfo]:
    """Check map background options before selecting render_route.provider.

    Each item reports id, available, image_export, configured, network, attribution,
    and note. none is offline and needs no credit. openstreetmap uses cached online
    street tiles and requires visible OSM credit. esri_satellite uses online imagery
    for personal static maps and requires visible Esri/data-source credit. google_satellite
    cannot be exported as an image here even if an API key is configured; use KML with
    Google Earth instead. available/configured describe local support and settings,
    not a live network probe; an online render can still fail if the network or provider
    is unavailable. Choose only providers with image_export=true for render_route.
    """
    return list_providers()


def load_internal_token() -> bytes:
    """Load a private token shared with the local MCP Gateway."""
    path_value = os.getenv("MCP_TOKEN_FILE")
    if not path_value:
        raise RuntimeError("MCP_TOKEN_FILE is required for HTTP transport")
    path = Path(path_value)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise RuntimeError("MCP token file must be a private regular file (mode 600)")
    token = path.read_text(encoding="ascii").strip()
    if len(token) < 32:
        raise RuntimeError("MCP token file is missing or too short")
    return token.encode("ascii")


class TokenGuard:
    def __init__(self, app, token: bytes):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            if scope.get("path") == "/health":
                await JSONResponse({"status": "ok"})(scope, receive, send)
                return
            supplied = next(
                (value for name, value in scope.get("headers", [])
                 if name.lower() == b"x-mcp-internal-token"),
                b"",
            )
            if not hmac.compare_digest(supplied, self.token):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app():
    return TokenGuard(
        mcp.http_app(path="/mcp", stateless_http=True, json_response=True),
        load_internal_token(),
    )


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "http":
        import uvicorn

        uvicorn.run(create_app(), host=os.getenv("MCP_HOST", "127.0.0.1"),
                    port=int(os.getenv("MCP_PORT", "8765")), log_level="warning")
    elif transport == "stdio":
        mcp.run(transport="stdio")
    else:
        raise ValueError(f"Unsupported MCP_TRANSPORT: {transport}")
