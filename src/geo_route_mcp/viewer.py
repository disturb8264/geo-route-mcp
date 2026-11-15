"""Small MCP Apps image viewer for clients that render UI resources."""

VIEWER_URI = "ui://geo-route/route-viewer-v1.html"

VIEWER_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>GPS route</title>
  <style>
    body { margin: 0; background: transparent; color: inherit; font: 14px system-ui, sans-serif; }
    main { width: 100%; text-align: center; }
    img { display: block; max-width: 100%; max-height: 80vh; width: auto; height: auto; margin: auto; }
    p { margin: 12px; }
  </style>
</head>
<body>
  <main><p id="status">Loading route image…</p><img id="route" alt="GPS route map" hidden></main>
  <script>
    const image = document.getElementById("route");
    const status = document.getElementById("status");
    function showResult(result) {
      const item = result?.content?.find(value =>
        value?.type === "image" && /^image\/(png|jpeg)$/.test(value.mimeType || "") && value.data
      );
      if (!item) return;
      image.src = `data:${item.mimeType};base64,${item.data}`;
      image.hidden = false;
      status.hidden = true;
    }
    let requestId = 0;
    window.addEventListener("message", event => {
      if (event.source !== window.parent || event.data?.jsonrpc !== "2.0") return;
      if (event.data.method === "ui/notifications/tool-result") showResult(event.data.params);
      if (event.data.id === requestId && event.data.result) {
        window.parent.postMessage({jsonrpc:"2.0", method:"ui/notifications/initialized", params:{}}, "*");
      }
    });
    const initial = window.openai?.toolResponseMetadata?.mcp_tool_result
      || window.openai?.toolResponseMetadata?.call_tool_result;
    showResult(initial);
    requestId = 1;
    window.parent.postMessage({jsonrpc:"2.0", id:requestId, method:"ui/initialize", params:{
      appInfo:{name:"geo-route-viewer", version:"1.0.0"},
      appCapabilities:{}, protocolVersion:"2026-01-26"
    }}, "*");
  </script>
</body>
</html>"""
