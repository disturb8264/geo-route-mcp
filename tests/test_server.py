import asyncio
import base64
import sys
from io import BytesIO
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from mcp.types import ImageContent
from PIL import Image as PILImage
from starlette.testclient import TestClient

from geo_route_mcp.server import create_app, load_internal_token, mcp


def test_mcp_tools_registered_and_callable():
    async def exercise():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools}
            assert names == {"render_route", "render_route_data", "convert_route",
                             "inspect_route", "list_map_providers"}
            by_name = {tool.name: tool for tool in tools}
            viewer_uri = "ui://geo-route/route-viewer-v1.html"
            assert by_name["render_route"].meta["ui"]["resourceUri"] == viewer_uri
            resources = await client.list_resources()
            assert any(str(resource.uri) == viewer_uri and
                       resource.mimeType == "text/html;profile=mcp-app" for resource in resources)
            viewer = await client.read_resource(viewer_uri)
            assert "ui/notifications/tool-result" in viewer[0].text
            assert "data:${item.mimeType};base64" in viewer[0].text
            for name in names:
                assert len(by_name[name].description) > 300
                for field in by_name[name].inputSchema.get("properties", {}).values():
                    assert field.get("description")
            source_schema = by_name["render_route"].inputSchema["properties"]["source"]
            for field in ("format", "content", "coordinate_order"):
                assert source_schema["properties"][field].get("description")
            assert "lat_lon" in source_schema["properties"]["coordinate_order"]["description"]
            assert "google_satellite" in by_name["list_map_providers"].description
            assert "data_base64" in by_name["render_route_data"].outputSchema["properties"]
            assert by_name["render_route_data"].outputSchema["properties"]["data_base64"]["description"]
            source = {"format": "coordinates", "content": [[37.5, 127.0], [37.6, 127.1]],
                      "coordinate_order": "lat_lon"}
            inspected = await client.call_tool("inspect_route", {"source": source})
            assert inspected.structured_content["point_count"] == 2
            converted = await client.call_tool("convert_route", {"source": source, "output_format": "geojson"})
            assert '"LineString"' in converted.structured_content["content"]
            rendered = await client.call_tool("render_route", {
                "source": source, "width": 240, "height": 320,
            })
            assert len(rendered.content) == 1
            assert isinstance(rendered.content[0], ImageContent)
            assert rendered.content[0].mimeType == "image/png"
            image_bytes = base64.b64decode(rendered.content[0].data)
            assert image_bytes.startswith(b"\x89PNG")
            with PILImage.open(BytesIO(image_bytes)) as image:
                assert image.size == (240, 320)
            jpeg = await client.call_tool("render_route", {
                "source": source, "width": 240, "height": 320, "output_format": "JPEG",
            })
            assert isinstance(jpeg.content[0], ImageContent)
            assert jpeg.content[0].mimeType == "image/jpeg"
            with PILImage.open(BytesIO(base64.b64decode(jpeg.content[0].data))) as image:
                assert image.size == (240, 320)
                assert image.format == "JPEG"
            legacy = await client.call_tool("render_route_data", {
                "source": source, "width": 240, "height": 320,
            })
            assert legacy.structured_content["mime_type"] == "image/png"
            assert legacy.structured_content["width"] == 240
            assert legacy.structured_content["height"] == 320
            assert base64.b64decode(legacy.structured_content["data_base64"]) == image_bytes
            listed = await client.call_tool("list_map_providers", {})
            assert listed.structured_content is not None

    asyncio.run(exercise())


def test_http_requires_private_token(tmp_path, monkeypatch):
    token_path = tmp_path / "token"
    token_path.write_text("a" * 64, encoding="ascii")
    token_path.chmod(0o600)
    monkeypatch.setenv("MCP_TOKEN_FILE", str(token_path))
    assert load_internal_token() == b"a" * 64

    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.post("/mcp").status_code == 401
        assert client.post("/mcp", headers={"X-MCP-Internal-Token": "wrong"}).status_code == 401

    token_path.chmod(0o644)
    with pytest.raises(RuntimeError, match="private regular file"):
        load_internal_token()


def test_stdio_server_connects_and_lists_tools():
    async def exercise():
        transport = StdioTransport(sys.executable, ["-m", "geo_route_mcp.server"],
                                   env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
        async with Client(transport) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools} == {
                "render_route", "render_route_data", "convert_route", "inspect_route", "list_map_providers"
            }
            result = await client.call_tool("render_route", {
                "source": {"format": "coordinates", "content": [[37.5, 127.0], [37.6, 127.1]],
                           "coordinate_order": "lat_lon"},
                "width": 240, "height": 320,
            })
            assert isinstance(result.content[0], ImageContent)
            assert result.content[0].mimeType == "image/png"
            with PILImage.open(BytesIO(base64.b64decode(result.content[0].data))) as image:
                assert image.size == (240, 320)

    asyncio.run(exercise())
