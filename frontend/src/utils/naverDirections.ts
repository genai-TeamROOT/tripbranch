/*
 * 역할: 네이버지도 "대중교통" 길찾기 딥링크를 만들고 연다(출발=현재 위치, 도착=장소).
 * 입력: deviceLocation("위도,경도" 문자열), 목적지 좌표·이름.
 * 출력: nmap:// 앱 딥링크를 열고, 앱이 없으면 네이버지도 웹 길찾기로 폴백한다.
 * 참고: API가 아니라 딥링크다 — 경로 계산은 네이버지도가 한다(키·비용 없음).
 *       appname은 검증되는 키가 아니라 "돌아가기"용 호출자 식별자라 현재 호스트명을
 *       그대로 쓴다.
 */

export interface NaverDirectionsArgs {
  /** 현재 위치. geolocation.ts가 만드는 "위도,경도" 문자열. */
  deviceLocation: string;
  destLat: number;
  destLng: number;
  destName: string;
}

/** 주소만 가진 항목을 네이버지도에서 바로 찾는다.
 *
 * 실시간 주차장 목록은 일부 민영 주차장에 좌표가 없고 주소만 있다. 이 경우에도
 * 사용자가 같은 이름의 다른 주차장을 고르지 않도록 주소를 검색어로 넘긴다.
 * 네이버지도 화면에서 현재 위치를 기준으로 길찾기를 바로 선택할 수 있다.
 */
export function openNaverMapSearch(destinationAddress: string, destinationName: string): boolean {
  const address = destinationAddress.trim();
  if (!address) return false;

  const query = encodeURIComponent(`${destinationName} ${address}`);
  const webUrl = `https://map.naver.com/p/search/${query}`;
  window.open(webUrl, "_blank", "noopener");
  return true;
}

function parseLatLng(value: string): { lat: number; lng: number } | null {
  const parts = value.split(",");
  if (parts.length !== 2) return null;
  const lat = Number(parts[0]);
  const lng = Number(parts[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return { lat, lng };
}

function callerAppName(): string {
  if (typeof window !== "undefined" && window.location.hostname) {
    return window.location.hostname;
  }
  return "tripbranch";
}

/**
 * 앱 딥링크와 웹 폴백 URL을 만든다. 출발 좌표가 없거나 형식이 깨졌으면 null.
 * 장소명·appname은 URL 인코딩해 값이 링크를 깨거나 뒤 파라미터를 자르지 않게 한다.
 */
export function buildNaverDirections(
  args: NaverDirectionsArgs,
): { appUrl: string; webUrl: string } | null {
  const origin = parseLatLng(args.deviceLocation);
  if (!origin) return null;

  const appname = encodeURIComponent(callerAppName());
  const dname = encodeURIComponent(args.destName);
  // 출발점 라벨. 네이버 화면에서 출발지가 "내 위치"로 표시된다.
  const sname = encodeURIComponent("내 위치");

  // route/public = 대중교통. (도보 route/walk, 자동차 route/car로 확장 가능)
  const appUrl =
    `nmap://route/public?slat=${origin.lat}&slng=${origin.lng}&sname=${sname}` +
    `&dlat=${args.destLat}&dlng=${args.destLng}&dname=${dname}&appname=${appname}`;

  // 네이버지도 웹 길찾기(대중교통). 형식: /출발/도착/-/transit (경도,위도,이름 순).
  const webUrl =
    `https://map.naver.com/p/directions/` +
    `${origin.lng},${origin.lat},${sname},,/${args.destLng},${args.destLat},${dname},,/-/transit`;

  return { appUrl, webUrl };
}

function isMobileBrowser(): boolean {
  if (typeof navigator === "undefined") return false;
  return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
}

/**
 * 대중교통 길찾기를 연다. 우리 서비스는 웹이므로 플랫폼에 맞춘다.
 * - 데스크톱: 네이버지도 앱이 없으니 웹 길찾기를 새 탭으로 바로 연다(지연 없음).
 * - 모바일: 앱 딥링크를 시도하고, 앱으로 전환되지 않으면(미설치) 웹으로 폴백한다.
 * 열 수 없으면(출발 좌표 없음) false.
 */
export function openNaverDirections(args: NaverDirectionsArgs): boolean {
  const urls = buildNaverDirections(args);
  if (!urls) return false;

  if (!isMobileBrowser()) {
    window.open(urls.webUrl, "_blank", "noopener");
    return true;
  }

  const fallbackTimer = window.setTimeout(() => {
    window.location.href = urls.webUrl;
  }, 1200);

  // 앱이 열리면 탭이 백그라운드로 가므로 폴백을 취소한다.
  const onHidden = () => {
    if (document.visibilityState === "hidden") {
      window.clearTimeout(fallbackTimer);
    }
  };
  document.addEventListener("visibilitychange", onHidden, { once: true });

  window.location.href = urls.appUrl;
  return true;
}
