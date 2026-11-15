"""Parse source formats without inventing locations or bridging track gaps."""

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET

from .models import Point, Route, RouteMetadata


def parse_coordinates(
    coordinates: Sequence[Sequence[float]],
    *,
    order: Literal["lat_lon", "lon_lat"],
    metadata: RouteMetadata | None = None,
) -> Route:
    """Accept pairs/triples with an explicit coordinate order; third value is elevation."""
    points: list[Point] = []
    for coordinate in coordinates:
        if len(coordinate) not in (2, 3):
            raise ValueError("each coordinate must have two or three numbers")
        first, second = coordinate[:2]
        latitude, longitude = (first, second) if order == "lat_lon" else (second, first)
        points.append(Point(latitude=latitude, longitude=longitude,
                            elevation_m=coordinate[2] if len(coordinate) == 3 else None))
    return Route(segments=[points], metadata=metadata or RouteMetadata())


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: Element, name: str) -> list[Element]:
    return [child for child in element if _local(child.tag) == name]


def _text(element: Element, name: str) -> str | None:
    for child in _children(element, name):
        return child.text.strip() if child.text else None
    return None


def _gpx_point(element: Element) -> Point:
    elevation = _text(element, "ele")
    time = _text(element, "time")
    return Point(latitude=element.attrib["lat"], longitude=element.attrib["lon"],
                 elevation_m=elevation, time=datetime.fromisoformat(time.replace("Z", "+00:00")) if time else None)


def parse_gpx(xml: str | bytes) -> Route:
    root = ET.fromstring(xml)
    if _local(root.tag) != "gpx":
        raise ValueError("expected GPX root")
    segments: list[list[Point]] = []
    name: str | None = None
    for child in root:
        kind = _local(child.tag)
        if kind == "trk":
            name = name or _text(child, "name")
            for segment in _children(child, "trkseg"):
                points = [_gpx_point(point) for point in _children(segment, "trkpt")]
                if points:
                    segments.append(points)
        elif kind == "rte":
            name = name or _text(child, "name")
            points = [_gpx_point(point) for point in _children(child, "rtept")]
            if points:
                segments.append(points)
    return Route(segments=segments, metadata=RouteMetadata(name=name))


def _kml_coordinates(text: str | None) -> list[Point]:
    points: list[Point] = []
    for item in (text or "").split():
        values = item.split(",")
        if len(values) not in (2, 3):
            raise ValueError("KML coordinates must be lon,lat[,alt]")
        points.append(Point(longitude=values[0], latitude=values[1],
                            elevation_m=values[2] if len(values) == 3 else None))
    return points


def parse_kml(xml: str | bytes) -> Route:
    root = ET.fromstring(xml)
    if _local(root.tag) != "kml":
        raise ValueError("expected KML root")
    segments: list[list[Point]] = []
    name: str | None = None
    for element in root.iter():
        if _local(element.tag) == "Document" and name is None:
            name = _text(element, "name")
        if _local(element.tag) == "LineString":
            coordinates = _text(element, "coordinates")
            points = _kml_coordinates(coordinates)
            if points:
                segments.append(points)
        elif _local(element.tag) == "Placemark":
            extended = _children(element, "ExtendedData")
            is_singleton = any(
                data.attrib.get("name") == "geo-route-segment"
                for item in extended for data in _children(item, "Data")
            )
            if is_singleton:
                for marker in _children(element, "Point"):
                    points = _kml_coordinates(_text(marker, "coordinates"))
                    if len(points) != 1:
                        raise ValueError("isolated KML route segment must contain one point")
                    segments.append(points)
    return Route(segments=segments, metadata=RouteMetadata(name=name))


def _geojson_lines(geometry: Mapping) -> list[list[Point]]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "LineString":
        lines = [coordinates]
    elif kind == "MultiLineString":
        lines = coordinates
    else:
        return []
    if not isinstance(lines, list):
        raise ValueError("invalid GeoJSON coordinates")
    return [parse_coordinates(line, order="lon_lat").points for line in lines if line]


def parse_geojson(data: str | bytes | Mapping) -> Route:
    obj = json.loads(data) if isinstance(data, (str, bytes)) else data
    if not isinstance(obj, Mapping):
        raise ValueError("GeoJSON must be an object")
    kind = obj.get("type")
    metadata = RouteMetadata()
    if kind == "FeatureCollection":
        features = obj.get("features")
        if not isinstance(features, list):
            raise ValueError("FeatureCollection requires features")
        segments = []
        for feature in features:
            if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
                raise ValueError("invalid GeoJSON feature")
            geometry = feature.get("geometry")
            if isinstance(geometry, Mapping):
                segments.extend(_geojson_lines(geometry))
    elif kind == "Feature":
        geometry = obj.get("geometry")
        segments = _geojson_lines(geometry) if isinstance(geometry, Mapping) else []
        properties = obj.get("properties")
        if isinstance(properties, Mapping):
            metadata = RouteMetadata.model_validate({
                key: value for key, value in properties.items()
                if key in RouteMetadata.model_fields
            })
    else:
        segments = _geojson_lines(obj)
    return Route(segments=segments, metadata=metadata)
