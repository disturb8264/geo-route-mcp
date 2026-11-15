from datetime import datetime, timezone

from geo_route_mcp import Point, Route, RouteMetadata, export_geojson, export_gpx, inspect, parse_geojson, parse_gpx


def test_distance_ignores_segment_gap_and_uses_supplied_times():
    route = Route(segments=[
        [Point(latitude=0, longitude=0, time=datetime(2026, 1, 1, tzinfo=timezone.utc)),
         Point(latitude=0, longitude=1)],
        [Point(latitude=30, longitude=30),
         Point(latitude=30, longitude=30.01, time=datetime(2026, 1, 1, 1, tzinfo=timezone.utc))],
    ])
    result = inspect(route)
    assert result.segment_count == 2
    assert result.point_count == 4
    assert 111 < result.distance_km < 113
    assert result.duration_seconds == 3600
    assert result.pace_seconds_per_km is not None


def test_gpx_geojson_round_trip_segments_and_elevation():
    route = Route(segments=[
        [Point(latitude=37, longitude=127, elevation_m=10), Point(latitude=38, longitude=128)],
        [Point(latitude=39, longitude=129)],
    ], metadata=RouteMetadata(name="Route A"))
    gpx = parse_gpx(export_gpx(route))
    geojson = parse_geojson(export_geojson(route))
    assert gpx.segments == route.segments
    assert geojson.segments == route.segments
    assert gpx.metadata.name == geojson.metadata.name == "Route A"
