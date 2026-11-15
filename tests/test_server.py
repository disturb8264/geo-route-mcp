import asyncio
import base64
import sys

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from starlette.testclient import TestClient

from geo_route_mcp.server import create_app, load_internal_token, mcp


def test_mcp_tools_registered_and_callable():
    async def exercise():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools}
            assert names == {"render_route", "convert_route", "inspect_route", "list_map_providers"}
            source = {"format": "coordinates", "content": [[37.5, 127.0], [37.6, 127.1]],
                      "coordinate_order": "lat_lon"}
            inspected = await client.call_tool("inspect_route", {"source": source})
            assert inspected.structured_content["point_count"] == 2
            converted = await client.call_tool("convert_route", {"source": source, "output_format": "geojson"})
            assert '"LineString"' in converted.structured_content["content"]
            rendered = await client.call_tool("render_route", {
                "source": source, "width": 128, "height": 128,
            })
            assert base64.b64decode(rendered.structured_content["data_base64"]).startswith(b"\x89PNG")
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
        transport = StdioTransport(sys.executable, ["-m", "geo_route_mcp.server"])
        async with Client(transport) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools} == {
                "render_route", "convert_route", "inspect_route", "list_map_providers"
            }

    asyncio.run(exercise())
