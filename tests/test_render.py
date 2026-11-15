from pathlib import Path

from geo_route_mcp import RenderOptions, RouteMetadata, parse_coordinates, parse_gpx, render_route


def test_sample_gpx_renders_offline_png():
    path = Path(__file__).resolve().parents[1] / "samples" / "seoul_route.gpx"
    route = parse_gpx(path.read_bytes())
    image = render_route(route, RenderOptions(width=320, height=240))
    assert image.size == (320, 240)
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0))[3] == 0
    assert image.getbbox() is not None


def test_antimeridian_route_is_visible_and_padded():
    route = parse_coordinates([[0, 179.9], [0, -179.9]], order="lat_lon")
    image = render_route(route, RenderOptions(width=400, height=200))
    bounds = image.getchannel("A").getbbox()
    assert bounds is not None
    assert bounds[0] > 0 and bounds[2] < 400


def test_jpeg_mode_and_preset():
    route = parse_coordinates([[37, 127]], order="lat_lon")
    options = RenderOptions.from_preset("instagram_square", output_format="JPEG")
    assert render_route(route, options).mode == "RGB"
    assert (options.width, options.height) == (1080, 1080)


def test_optional_metadata_panel():
    route = parse_coordinates([[37, 127], [38, 128]], order="lat_lon",
                              metadata=RouteMetadata(name="Morning run", distance_km=5.0))
    plain = render_route(route, RenderOptions(width=320, height=240))
    labeled = render_route(route, RenderOptions(width=320, height=240, show_metadata=True))
    assert plain.getpixel((0, 0))[3] == 0
    assert labeled.getpixel((0, 0)) == (255, 255, 255, 255)


def test_default_route_color_is_coral_red():
    assert RenderOptions().line_color == "#FF4F3C"


def test_overlapping_start_and_finish_remain_distinct():
    route = parse_coordinates([[37, 127], [37, 127]], order="lat_lon")
    image = render_route(route, RenderOptions(width=320, height=240))
    colors = [pixel[:3] for pixel in image.getdata()]
    assert (32, 191, 107) in colors  # start green
    assert (235, 59, 90) in colors  # finish red
