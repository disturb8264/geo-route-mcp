"""Common route model. Every segment contains actual supplied GPS positions."""

from datetime import datetime
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    elevation_m: float | None = None
    time: datetime | None = None

    @field_validator("latitude", "longitude", "elevation_m")
    @classmethod
    def finite(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("coordinates and elevation must be finite")
        return value


class RouteMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    date: datetime | None = None
    distance_km: float | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    pace_seconds_per_km: float | None = Field(default=None, ge=0)


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[list[Point]]
    metadata: RouteMetadata = Field(default_factory=RouteMetadata)

    @model_validator(mode="after")
    def has_points(self) -> "Route":
        if not self.segments or any(not segment for segment in self.segments):
            raise ValueError("route requires at least one nonempty segment")
        return self

    @property
    def points(self) -> list[Point]:
        return [point for segment in self.segments for point in segment]
