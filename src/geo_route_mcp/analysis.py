"""Measurements derived only from supplied GPS points."""

from datetime import datetime
from math import asin, cos, radians, sin, sqrt

from pydantic import BaseModel, Field

from .models import Point, Route

EARTH_RADIUS_KM = 6371.0088


class RouteInspection(BaseModel):
    valid: bool = Field(description="True for a successfully parsed route; invalid input raises an error.")
    segment_count: int = Field(description="Number of distinct route segments; gaps are not connected.")
    point_count: int = Field(description="Total count of actual GPS points across all segments.")
    min_latitude: float = Field(description="Southernmost supplied latitude in degrees.")
    max_latitude: float = Field(description="Northernmost supplied latitude in degrees.")
    min_longitude: float = Field(description="Westernmost numeric longitude in degrees.")
    max_longitude: float = Field(description="Easternmost numeric longitude in degrees.")
    crosses_antimeridian: bool = Field(description="Whether consecutive points cross the +/-180-degree meridian.")
    distance_km: float = Field(description="Great-circle distance in km, summed only within each segment.")
    start_time: datetime | None = Field(default=None, description="First supplied point timestamp, if any.")
    end_time: datetime | None = Field(default=None, description="Last supplied point timestamp, if any.")
    duration_seconds: float | None = Field(
        default=None, description="Nonnegative difference between comparable first/last supplied timestamps."
    )
    pace_seconds_per_km: float | None = Field(
        default=None, description="Duration divided by distance when duration exists and distance is positive."
    )


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
