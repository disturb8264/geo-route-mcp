# Geo Route MCP 작업 지침

- 이 프로젝트는 서비스 독립적인 GPS 경로 처리 라이브러리와 MCP 서버로 발전시킨다.
- GPS 점을 추측하거나 생성하지 않는다. 빈 경로는 오류로 처리한다.
- GPX 트랙 세그먼트와 GeoJSON MultiLineString의 구간 경계를 보존한다.
- 지도 공급자와 네트워크 접근은 명시적 선택 사항으로 둔다. 유료 API 호출은 기본적으로 비활성화한다.
- Garmin 프로젝트, 데이터베이스, 개인 데이터에 의존하지 않는다.
- 테스트에는 `samples/`의 공개 예시 좌표만 사용한다.
- 기능 변경 후 `pytest`를 실행하고 README의 구현 상태를 갱신한다.
- Google Maps Static API 이미지를 파일로 저장하거나 MCP 이미지 출력으로 재호스팅하지 않는다. Google Earth KML 내보내기 경로를 유지한다.
- OpenStreetMap 공개 타일은 현재 요청 범위만 가져오고 캐시와 출처 표시를 유지한다.
- Esri World Imagery 정적 이미지는 개인용으로 사용하고 서비스 제공자·데이터 제공자 출처를 결과에 표시한다.
