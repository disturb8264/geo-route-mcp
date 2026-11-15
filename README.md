# Geo Route MCP

서비스 독립적인 GPS 경로 처리 MCP 서버입니다. 좌표 배열, GPX, KML, GeoJSON을 공통 모델로 읽고, 경로 검사·형식 변환·PNG/JPEG 렌더링을 제공합니다. Garmin 등 특정 서비스와 연결하지 않으며 입력에 없는 좌표를 만들지 않습니다.

## 설치

Python 3.12 이상:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[mcp,test]'
.venv/bin/pytest
.venv/bin/python -m geo_route_mcp.server
```

마지막 명령은 MCP stdio 서버를 시작합니다. MCP 클라이언트 설정 예시는 [examples/mcp_client.json](examples/mcp_client.json)입니다. 클라이언트가 GPS 본문을 도구 입력으로 전달하므로 서버가 다른 MCP나 운동 서비스에 직접 연결할 필요가 없습니다.

## MCP 도구

모든 도구의 `source`는 다음 구조입니다. `content`는 GPS 형식일 때 문자열이며, 좌표 배열일 때 숫자 쌍/세 쌍의 배열입니다.

```json
{"format":"coordinates","content":[[37.5665,126.9780],[37.5683,126.9821]],"coordinate_order":"lat_lon"}
```

`coordinate_order`는 배열에 필수입니다. GPX는 `lat`/`lon` 속성, KML과 GeoJSON은 `longitude,latitude` 순서를 사용합니다.

| 도구 | 주요 입력 | 결과 |
| --- | --- | --- |
| `render_route` | `source`, `provider` (`none`/`openstreetmap`/`esri_satellite`), `preset` 또는 `width`·`height`, 색·두께, `output_format`, `show_metadata` | MIME 유형, base64 PNG/JPEG, 크기, 공급자, 출처 |
| `convert_route` | `source`, `output_format` (`gpx`/`kml`/`geojson`) | 변환한 텍스트와 MIME 유형 |
| `inspect_route` | `source` | 좌표 범위, 점·구간 수, 거리, 시간, 페이스, 날짜 변경선 통과 여부 |
| `list_map_providers` | 없음 | 공급자 사용 가능 상태, 네트워크 사용, 이미지 내보내기 가능 여부, 출처 |

경로가 비어 있거나 위도·경도가 허용 범위를 벗어나면 오류를 반환합니다. GPX 트랙 세그먼트, KML LineString, GeoJSON MultiLineString의 경계를 보존하므로 구간 사이에 선을 그리지 않습니다. 거리도 구간별로 계산합니다.

## CLI

```bash
.venv/bin/python -m geo_route_mcp samples/seoul_route.gpx route.png --preset instagram_portrait
.venv/bin/python -m geo_route_mcp samples/seoul_route.gpx route-osm.png --provider openstreetmap
.venv/bin/python -m geo_route_mcp samples/seoul_route.gpx route-satellite.png --provider esri_satellite
.venv/bin/python -m geo_route_mcp samples/seoul_route.gpx route.kml
.venv/bin/python -m geo_route_mcp samples/seoul_route.gpx route.geojson
```

입력 파일: `.gpx`, `.kml`, `.geojson`, `.json`. 출력: `.png`, `.jpg`, `.jpeg`, `.gpx`, `.kml`, `.geojson`, `.json`. 프리셋: `instagram_portrait` 1080×1350, `instagram_square` 1080×1080, `landscape` 1920×1080. `--width`, `--height`, `--line-color`, `--line-width`, `--show-metadata`도 지원합니다. PNG 기본 배경은 투명하며 JPEG는 흰 배경입니다.

기본 경로선 색은 위성 영상 위에서 잘 보이는 선명한 주황빛 빨강 `#FF4F3C`입니다. 필요하면 `--line-color` 또는 MCP의 `line_color`로 바꿀 수 있습니다.

출발점과 도착점은 흰 테두리가 있는 서로 다른 기호로 표시합니다. 순환 경로처럼 두 좌표가 가까우면 기호를 분리하고 가는 선으로 실제 좌표에 연결합니다.

`samples/seoul_route.kml`을 Google Earth에서 열면 샘플 경로를 확인할 수 있습니다. 개인적인 비상업적 정적 이미지 내보내기는 [Google의 Geo 지침](https://about.google/brand-resource-center/products-and-services/geo-guidelines/)에 따라 출처를 유지하세요.

## 지도 배경과 비용

- `none`: 네트워크와 API 키 없이 배경 없는 경로 이미지.
- `openstreetmap`: 요청한 이미지 범위에 필요한 타일만 가져오고 HTTP 캐시에 보관합니다. 출처를 이미지 안에 표시합니다. 기본 타일 서버는 [OSMF 타일 정책](https://operations.osmfoundation.org/policies/tiles/)에 따라 이용하며 대량 요청·사전 다운로드에는 사용하지 마세요. 캐시 위치는 `GEO_ROUTE_TILE_CACHE_DIR`로 바꿀 수 있습니다.
- `esri_satellite`: Esri World Imagery 정적 영상 한 장을 요청하고 실제 GPS 경로를 그립니다. 개인용 정적 이미지에 대한 [Esri 이용 조건](https://doc.arcgis.com/en/arcgis-online/reference/static-maps.htm)에 따라 Esri와 데이터 제공자 출처를 이미지에 표시합니다. 이미지 한 변은 최대 4096픽셀입니다.
- `google_satellite`: API 키와 사용 설정을 위한 `.env` 구성이 있으나, Google Maps Static API 이미지의 저장·재호스팅 제한 때문에 PNG/JPEG 내보내기 공급자로는 제공하지 않습니다. [Google Maps Platform FAQ](https://developers.google.com/maps/faq). Google 위성 경로를 개인용 정적 이미지로 쓰려면 KML을 Earth에서 열어 내보내는 경로를 사용합니다.

`.env`는 Git과 Docker 빌드에서 제외됩니다. `GOOGLE_MAPS_API_KEY`와 `GOOGLE_MAPS_ENABLED`를 담을 수 있지만 현재 MCP 이미지 도구는 Google API를 호출하지 않습니다. 유료 API 호출은 기본적으로 비활성화됩니다.

## Docker

```bash
docker build -t geo-route-mcp .
docker run --rm -i geo-route-mcp
docker run --rm -v "$PWD:/data" geo-route-mcp python -m geo_route_mcp /data/samples/seoul_route.gpx /data/route.png
```

첫 번째 `docker run`은 stdio MCP 서버입니다. Docker로 OpenStreetMap 공급자를 반복 사용할 때는 `/root/.cache/geo-route-mcp`에 영구 볼륨을 연결해 타일 캐시를 유지하세요.
