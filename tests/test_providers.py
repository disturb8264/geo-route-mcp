from io import BytesIO
from urllib.parse import parse_qs, urlparse

from PIL import Image

from geo_route_mcp import RenderOptions, parse_coordinates
from geo_route_mcp.providers import EsriSatelliteProvider, OSMTileProvider, list_providers


class FakeTiles(OSMTileProvider):
    def __init__(self):
        self.calls = []

    def tile(self, zoom, x, y):
        self.calls.append((zoom, x, y))
        return Image.new("RGB", (256, 256), "#e0e0e0")


def test_osm_render_requests_viewport_only_and_attribution():
    route = parse_coordinates([[37.5665, 126.978], [37.5683, 126.9821]], order="lat_lon")
    provider = FakeTiles()
    image = provider.render(route, RenderOptions(width=400, height=300))
    assert image.size == (400, 300)
    assert 1 <= len(provider.calls) <= 64
    assert image.getpixel((0, 0)) == (224, 224, 224)
    assert image.getpixel((399, 299)) == (255, 255, 255)


def test_provider_list_marks_google_as_nonexportable():
    providers = {item.id: item for item in list_providers()}
    assert providers["none"].image_export
    assert providers["openstreetmap"].attribution
    assert providers["esri_satellite"].image_export
    assert not providers["google_satellite"].image_export


def test_esri_satellite_uses_route_extent_and_keeps_attribution(monkeypatch):
    route = parse_coordinates([[37.52, 126.91], [37.54, 126.93]], order="lat_lon")
    captured = {}

    def fake_open(request, timeout):
        captured["query"] = parse_qs(urlparse(request.full_url).query)
        image = Image.new("RGB", (800, 600), "#808080")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    monkeypatch.setattr("geo_route_mcp.providers.urlopen", fake_open)
    image = EsriSatelliteProvider().render(route, RenderOptions(width=800, height=600))
    assert captured["query"]["bboxSR"] == ["3857"]
    assert image.getpixel((400, 300)) != (128, 128, 128)
    assert image.getpixel((799, 599)) != (128, 128, 128)
