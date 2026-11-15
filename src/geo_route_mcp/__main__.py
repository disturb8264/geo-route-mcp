"""Small offline CLI for checking and rendering route files."""

import argparse
from pathlib import Path

from .exporters import export_geojson, export_gpx, export_kml
from .parsers import parse_geojson, parse_gpx, parse_kml
from .providers import EsriSatelliteProvider, OSMTileProvider
from .render import PRESETS, RenderOptions, render_route


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a route image or convert GPS formats")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--preset", choices=PRESETS)
    parser.add_argument("--provider", choices=("none", "openstreetmap", "esri_satellite"), default="none")
    parser.add_argument("--line-color", default="#FF4F3C")
    parser.add_argument("--line-width", type=int, default=6)
    parser.add_argument("--show-metadata", action="store_true")
    args = parser.parse_args()
    parsers = {".gpx": parse_gpx, ".kml": parse_kml, ".geojson": parse_geojson, ".json": parse_geojson}
    suffix = args.input.suffix.lower()
    if suffix not in parsers:
        parser.error("input must be .gpx, .kml, .geojson, or .json")
    route = parsers[suffix](args.input.read_bytes())
    output_suffix = args.output.suffix.lower()
    if output_suffix in (".kml", ".gpx", ".geojson", ".json"):
        exporters = {".kml": lambda value: export_kml(value, line_color=args.line_color,
                                                        line_width=args.line_width),
                     ".gpx": export_gpx, ".geojson": export_geojson, ".json": export_geojson}
        args.output.write_text(exporters[output_suffix](route), encoding="utf-8")
        return
    output_format = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}.get(output_suffix)
    if output_format is None:
        parser.error("output must be .kml, .gpx, .geojson, .png, .jpg, or .jpeg")
    preset_width, preset_height = PRESETS[args.preset] if args.preset else (1080, 1080)
    options = RenderOptions(width=args.width or preset_width, height=args.height or preset_height,
                            line_color=args.line_color, line_width=args.line_width,
                            output_format=output_format, show_metadata=args.show_metadata)
    if args.provider == "openstreetmap":
        image = OSMTileProvider().render(route, options)
    elif args.provider == "esri_satellite":
        image = EsriSatelliteProvider().render(route, options)
    else:
        image = render_route(route, options)
    image.save(args.output, format=output_format)


if __name__ == "__main__":
    main()
