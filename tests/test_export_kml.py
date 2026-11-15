from pathlib import Path
from xml.etree import ElementTree as ET

from geo_route_mcp import Point, Route, RouteMetadata, export_kml, parse_gpx, parse_kml


def test_kml_export_round_trip_preserves_segments_coordinates_and_name():
    route = Route(
        segments=[
            [Point(latitude=37, longitude=127, elevation_m=12), Point(latitude=38, longitude=128)],
            [Point(latitude=39, longitude=129)],
        ],
        metadata=RouteMetadata(name="A & B"),
    )
    xml = export_kml(route, line_color="#123456", line_width=4)
    root = ET.fromstring(xml)
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    assert root.find(".//k:LineStyle/k:color", ns).text == "ff563412"
    assert len(root.findall(".//k:LineString", ns)) == 1
    restored = parse_kml(xml)
    assert restored.segments == route.segments
    assert restored.metadata.name == "A & B"


def test_sample_gpx_exports_earth_kml():
    sample = Path(__file__).resolve().parents[1] / "samples" / "seoul_route.gpx"
    route = parse_gpx(sample.read_bytes())
    restored = parse_kml(export_kml(route))
    assert [(p.latitude, p.longitude, p.elevation_m) for p in restored.points] == [
        (p.latitude, p.longitude, p.elevation_m) for p in route.points
    ]
    assert restored.metadata.name == "Seoul sample"
