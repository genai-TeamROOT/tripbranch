/*
 * 역할: 기기 위치를 아직 실제 GPS로 받지 않는 동안 쓰는 개발용 기본 좌표를 제공한다.
 * 입력: 없음.
 * 출력: "위도,경도" 형식 문자열.
 * 호출 시점: HomePage/ChatPage가 /api/chat에 device_location을 실을 때 사용한다.
 *
 * AgentRuntimeDebugPanel의 기본값과 같은 지점(경복궁)이다. 이 값이 있어야 세션에
 * GPS가 심겨 날씨 조회 경로가 동작한다.
 * TODO: navigator.geolocation 연동이 들어오면 이 상수는 fallback으로만 남긴다.
 */

export const DEFAULT_DEVICE_LOCATION = "37.5788,126.9770";
