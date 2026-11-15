import pytest
from pydantic import ValidationError

from geo_route_mcp import parse_coordinates, parse_geojson, parse_gpx, parse_kml


def test_coordinates_require_order_and_real_points():
    route = parse_coordinates([[37.5, 127.0, 12], [37.6, 127.1]], order="lat_lon")
    assert route.points[0].elevation_m == 12
    assert route.points[0].latitude == 37.5
    with pytest.raises(ValidationError):
        parse_coordinates([], order="lat_lon")
    with pytest.raises(ValidationError):
        parse_coordinates([[127.0, 37.5]], order="lat_lon")
    with pytest.raises(TypeError):
        parse_coordinates([[37.5, 127.0]])


def test_gpx_preserves_track_segments_and_time():
    xml = '''<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><name>A</name>
    <trkseg><trkpt lat="37" lon="127"><time>2026-01-01T00:00:00Z</time></trkpt></trkseg>
    <trkseg><trkpt lat="38" lon="128"/></trkseg></trk></gpx>'''
    route = parse_gpx(xml)
    assert len(route.segments) == 2
    assert route.metadata.name == "A"
    assert route.points[0].time.year == 2026


def test_kml_linestring_uses_lon_lat_order():
    xml = '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><LineString><coordinates>127,37,10 128,38</coordinates></LineString></Placemark></Document></kml>'
    route = parse_kml(xml)
    assert [(p.latitude, p.longitude) for p in route.points] == [(37, 127), (38, 128)]


def test_geojson_multiline_and_no_fabricated_point():
    route = parse_geojson({"type": "MultiLineString", "coordinates": [[[127, 37], [128, 38]], [[129, 39]]]})
    assert len(route.segments) == 2
    with pytest.raises(ValidationError):
        parse_geojson({"type": "Point", "coordinates": [127, 37]})


def test_xml_entity_is_rejected():
    with pytest.raises(Exception):
        parse_gpx('<!DOCTYPE gpx [<!ENTITY x "a">]><gpx>&x;</gpx>')
