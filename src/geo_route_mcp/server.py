"""FastMCP stdio server. Map API costs are disabled for image exports."""

import base64
from io import BytesIO
from typing import Literal

from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, model_validator

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


if __name__ == "__main__":
    mcp.run()
