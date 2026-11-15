"""Measurements derived only from supplied GPS points."""

from datetime import datetime
from math import asin, cos, radians, sin, sqrt

from pydantic import BaseModel

from .models import Point, Route

EARTH_RADIUS_KM = 6371.0088


class RouteInspection(BaseModel):
    valid: bool
    segment_count: int
    point_count: int
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float
    crosses_antimeridian: bool
    distance_km: float
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: float | None = None
    pace_seconds_per_km: float | None = None


def _distance(a: Point, b: Point) -> float:
    lat1, lat2 = radians(a.latitude), radians(b.latitude)
    dlat = lat2 - lat1
    dlon = radians((b.longitude - a.longitude + 180) % 360 - 180)
    hav = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(min(1.0, sqrt(hav)))


def inspect(route: Route) -> RouteInspection:
    points = route.points
    distance = sum(_distance(a, b) for segment in route.segments
                   for a, b in zip(segment, segment[1:]))
    crosses = any(abs(b.longitude - a.longitude) > 180
                  for segment in route.segments for a, b in zip(segment, segment[1:]))
    timed = [point.time for point in points if point.time is not None]
    start_time = timed[0] if timed else None
    end_time = timed[-1] if timed else None
    try:
        duration = max(0.0, (end_time - start_time).total_seconds()) if start_time and end_time else None
    except TypeError:
        duration = None
    return RouteInspection(
        valid=True, segment_count=len(route.segments), point_count=len(points),
        min_latitude=min(p.latitude for p in points),
        max_latitude=max(p.latitude for p in points),
        min_longitude=min(p.longitude for p in points),
        max_longitude=max(p.longitude for p in points),
        crosses_antimeridian=crosses, distance_km=distance,
        start_time=start_time, end_time=end_time, duration_seconds=duration,
        pace_seconds_per_km=duration / distance if duration is not None and distance > 0 else None,
    )
