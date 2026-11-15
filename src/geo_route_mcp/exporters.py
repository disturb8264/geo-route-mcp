"""Export the common route model for opening in Google Earth and other KML viewers."""

import json
from xml.etree import ElementTree as ET

from PIL import ImageColor

from .models import Point, Route

KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)


def _tag(name: str) -> str:
    return f"{{{KML_NS}}}{name}"


def _coord(point: Point) -> str:
    values = [str(point.longitude), str(point.latitude)]
    if point.elevation_m is not None:
        values.append(str(point.elevation_m))
    return ",".join(values)


def _kml_color(color: str) -> str:
    rgb = ImageColor.getrgb(color)
    red, green, blue = rgb[:3]
    alpha = rgb[3] if len(rgb) == 4 else 255
    return f"{alpha:02x}{blue:02x}{green:02x}{red:02x}"


def export_kml(route: Route, *, line_color: str = "#FF4F3C", line_width: int = 6) -> str:
    """Return Earth-ready KML, preserving segment boundaries and source coordinates."""
    if line_width < 1:
        raise ValueError("line_width must be positive")
    ET.register_namespace("", KML_NS)
    root = ET.Element(_tag("kml"))
    document = ET.SubElement(root, _tag("Document"))
    ET.SubElement(document, _tag("name")).text = route.metadata.name or "GPS route"
    style = ET.SubElement(document, _tag("Style"), id="route-line")
    line_style = ET.SubElement(style, _tag("LineStyle"))
    ET.SubElement(line_style, _tag("color")).text = _kml_color(line_color)
    ET.SubElement(line_style, _tag("width")).text = str(line_width)

    for index, segment in enumerate(route.segments, 1):
        placemark = ET.SubElement(document, _tag("Placemark"))
        ET.SubElement(placemark, _tag("name")).text = f"Segment {index}"
        if len(segment) > 1:
            ET.SubElement(placemark, _tag("styleUrl")).text = "#route-line"
            line = ET.SubElement(placemark, _tag("LineString"))
            ET.SubElement(line, _tag("tessellate")).text = "1"
            ET.SubElement(line, _tag("coordinates")).text = " ".join(map(_coord, segment))
        else:
            # Earth displays isolated GPS points as Point geometries.
            extended = ET.SubElement(placemark, _tag("ExtendedData"))
            data = ET.SubElement(extended, _tag("Data"), name="geo-route-segment")
            ET.SubElement(data, _tag("value")).text = "1"
            point = ET.SubElement(placemark, _tag("Point"))
            ET.SubElement(point, _tag("coordinates")).text = _coord(segment[0])

    for label, point in (("Start", route.segments[0][0]), ("Finish", route.segments[-1][-1])):
        placemark = ET.SubElement(document, _tag("Placemark"))
        ET.SubElement(placemark, _tag("name")).text = label
        marker = ET.SubElement(placemark, _tag("Point"))
        ET.SubElement(marker, _tag("coordinates")).text = _coord(point)

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def export_geojson(route: Route) -> str:
    """Write RFC 7946 longitude/latitude coordinates without joining segments."""
    lines = [
        [[p.longitude, p.latitude] if p.elevation_m is None else
         [p.longitude, p.latitude, p.elevation_m] for p in segment]
        for segment in route.segments
    ]
    geometry = {"type": "LineString", "coordinates": lines[0]} if len(lines) == 1 else {
        "type": "MultiLineString", "coordinates": lines,
    }
    properties = route.metadata.model_dump(mode="json", exclude_none=True)
    return json.dumps({"type": "Feature", "properties": properties, "geometry": geometry},
                      ensure_ascii=False, separators=(",", ":"))


def export_gpx(route: Route) -> str:
    """Write GPX 1.1 track segments with optional elevation and timestamps."""
    namespace = "http://www.topografix.com/GPX/1/1"
    ET.register_namespace("", namespace)
    def tag(name: str) -> str:
        return f"{{{namespace}}}{name}"
    root = ET.Element(tag("gpx"), version="1.1", creator="geo-route-mcp")
    track = ET.SubElement(root, tag("trk"))
    if route.metadata.name:
        ET.SubElement(track, tag("name")).text = route.metadata.name
    for segment in route.segments:
        track_segment = ET.SubElement(track, tag("trkseg"))
        for point in segment:
            element = ET.SubElement(track_segment, tag("trkpt"),
                                    lat=str(point.latitude), lon=str(point.longitude))
            if point.elevation_m is not None:
                ET.SubElement(element, tag("ele")).text = str(point.elevation_m)
            if point.time is not None:
                ET.SubElement(element, tag("time")).text = point.time.isoformat().replace("+00:00", "Z")
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
