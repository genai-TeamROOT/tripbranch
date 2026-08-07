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
