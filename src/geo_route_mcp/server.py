"""FastMCP stdio and authenticated HTTP server."""

import base64
import hmac
import os
import stat
from io import BytesIO
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, model_validator
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

    format: Literal["coordinates", "gpx", "kml", "geojson"]
    content: str | list[list[float]]
    coordinate_order: Literal["lat_lon", "lon_lat"] | None = None

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
    mime_type: str
    data_base64: str
    width: int
    height: int
    provider: str
    attribution: str | None = None


class ConvertedRoute(BaseModel):
    format: Literal["gpx", "kml", "geojson"]
    mime_type: str
    content: str


@mcp.tool(name="render_route")
def render_route_tool(
    source: RouteSource,
    provider: Literal["none", "openstreetmap", "esri_satellite"] = "none",
    preset: Literal["instagram_portrait", "instagram_square", "landscape"] | None = None,
    width: int | None = None,
    height: int | None = None,
    output_format: Literal["PNG", "JPEG"] = "PNG",
    line_color: str = "#FF4F3C",
    line_width: int = 6,
    show_metadata: bool = False,
) -> RenderedRoute:
    """Render real GPS positions as a background-free or attributed OSM image."""
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
    return RenderedRoute(mime_type="image/png" if output_format == "PNG" else "image/jpeg",
                         data_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
                         width=image.width, height=image.height, provider=provider,
                         attribution=attribution)


@mcp.tool(name="convert_route")
def convert_route_tool(source: RouteSource, output_format: Literal["gpx", "kml", "geojson"]) -> ConvertedRoute:
    """Convert GPS positions between GPX, KML, and GeoJSON without adding points."""
    route = source.route()
    content = {"gpx": export_gpx, "kml": export_kml, "geojson": export_geojson}[output_format](route)
    mime = {"gpx": "application/gpx+xml", "kml": "application/vnd.google-earth.kml+xml",
            "geojson": "application/geo+json"}[output_format]
    return ConvertedRoute(format=output_format, mime_type=mime, content=content)


@mcp.tool(name="inspect_route")
def inspect_route_tool(source: RouteSource) -> RouteInspection:
    """Report route bounds, segment count, geodesic length, and available timing."""
    return inspect(source.route())


@mcp.tool(name="list_map_providers")
def list_map_providers_tool() -> list[ProviderInfo]:
    """List background options, availability, network use, and attribution."""
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
