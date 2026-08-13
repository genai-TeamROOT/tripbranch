/*
 * 브라우저 위치 권한 요청을 한 곳에서 관리한다.
 * 메인 추천 흐름과 개발용 Agent Runtime 패널이 같은 옵션·오류 문구를 사용한다.
 */

const GEOLOCATION_OPTIONS: PositionOptions = {
  // 데스크톱은 GPS 칩이 없어 고정밀 모드에서 타임아웃이 잦다.
  enableHighAccuracy: false,
  timeout: 20000,
  maximumAge: 60000,
};

/**
 * 로컬 Vite 개발 서버에서만 쓸 수 있는 고정 좌표다. Codex 같은 자동화 브라우저는
 * macOS 위치 권한 팝업을 승인할 수 없는 경우가 있어, 명시적으로 설정했을 때만
 * 브라우저 Geolocation API 호출을 건너뛴다. 배포 빌드에서는 항상 null이다.
 */
function testDeviceLocation(): string | null {
  if (!import.meta.env.DEV) return null;
  const value = import.meta.env.VITE_TEST_DEVICE_LOCATION?.trim();
  if (!value) return null;

  const [latitude, longitude, ...rest] = value.split(",").map(Number);
  if (
    rest.length > 0 ||
    !Number.isFinite(latitude) ||
    !Number.isFinite(longitude) ||
    latitude < -90 ||
    latitude > 90 ||
    longitude < -180 ||
    longitude > 180
  ) {
    console.warn("VITE_TEST_DEVICE_LOCATION 형식이 올바르지 않아 브라우저 위치를 사용합니다.");
    return null;
  }
  return `${latitude},${longitude}`;
}

function locationErrorMessage(error: GeolocationPositionError) {
  if (error.code === error.TIMEOUT) {
    return (
      "위치 조회 시간이 초과됐어요. macOS 설정 > 개인정보 보호 및 보안 > 위치 서비스에서 " +
      "브라우저 권한이 켜져 있는지 확인해주세요."
    );
  }
  if (error.code === error.PERMISSION_DENIED) {
    return "위치 권한이 필요해요. 브라우저 주소창의 위치 권한을 허용한 뒤 다시 시도해주세요.";
  }
  return `위치를 가져오지 못했어요: ${error.message}`;
}

export function getBrowserDeviceLocation(): Promise<string> {
  const testLocation = testDeviceLocation();
  if (testLocation) return Promise.resolve(testLocation);

  if (!("geolocation" in navigator)) {
    return Promise.reject(new Error("이 브라우저는 위치 조회를 지원하지 않아요."));
  }

  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude } = position.coords;
        resolve(`${latitude},${longitude}`);
      },
      (error) => reject(new Error(locationErrorMessage(error))),
      GEOLOCATION_OPTIONS,
    );
  });
}
