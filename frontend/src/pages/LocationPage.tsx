/*
 * 역할: 지금 추천에 쓰이는 기기 위치 상태를 보여주고, 다시 받아올 수 있게 한다.
 * 입력: TripContext의 device_location/device_location_captured_at.
 * 출력: 좌표·마지막 확인 시각, "위치 다시 가져오기" 버튼(성공 시 SET_DEVICE_LOCATION
 *   디스패치 — 다음 채팅 턴부터 바로 반영된다).
 * 호출 시점: 사이드바 "위치 설정"에서 바텀시트로 열린다(DESIGN_SYSTEM.md §5).
 *
 * 수동 주소 입력이나 지역 선택은 아직 없다 — 이 앱이 가진 위치 개념은 브라우저
 * GPS 한 가지뿐이라, 그 상태를 보여주고 새로고침하는 것만 실제로 만들었다.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { MapPin, RefreshCw } from "lucide-react";
import { AppHeader } from "../components/layout/AppHeader";
import { useTripDispatch, useTripState } from "../state/TripContext";
import { getLocationAgeMinutes } from "../utils/locationRefresh";
import { getBrowserDeviceLocation } from "../utils/geolocation";

export function LocationPage() {
  const navigate = useNavigate();
  const state = useTripState();
  const dispatch = useTripDispatch();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const ageMinutes = getLocationAgeMinutes(state.device_location_captured_at);

  async function handleRefresh() {
    if (isRefreshing) return;
    setIsRefreshing(true);
    setErrorMessage(null);
    try {
      const deviceLocation = await getBrowserDeviceLocation({ forceFresh: true });
      dispatch({
        type: "SET_DEVICE_LOCATION",
        payload: { deviceLocation, capturedAt: Date.now() },
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "위치를 가져오지 못했어요.");
    } finally {
      setIsRefreshing(false);
    }
  }

  return (
    <main className="flex h-full flex-col overflow-y-auto">
      <AppHeader onBack={() => navigate(-1)} />
      <div className="flex flex-1 flex-col gap-4 px-4 pb-10">
        <h1 className="text-[24px] font-bold leading-snug text-ink">위치 설정</h1>

        <section className="flex items-center gap-3 rounded-2xl bg-white p-4 shadow-resting">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-sky-light text-brand">
            <MapPin size={20} />
          </span>
          <div className="min-w-0 flex-1">
            {state.device_location ? (
              <>
                <p className="truncate text-sm font-semibold text-ink">{state.device_location}</p>
                <p className="mt-0.5 text-xs text-muted">
                  {ageMinutes === null ? "방금 확인했어요" : `${ageMinutes}분 전에 확인했어요`}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted">아직 위치를 가져오지 않았어요</p>
            )}
          </div>
        </section>

        {errorMessage && (
          <p role="alert" className="text-sm text-rust">
            {errorMessage}
          </p>
        )}

        <button
          type="button"
          disabled={isRefreshing}
          onClick={() => void handleRefresh()}
          className="flex items-center justify-center gap-2 rounded-full bg-brand py-3 text-sm font-semibold text-white transition hover:bg-brand-deep active:scale-[0.98] disabled:opacity-50"
        >
          <RefreshCw size={16} className={isRefreshing ? "animate-spin" : undefined} />
          {isRefreshing ? "위치를 가져오는 중이에요…" : "위치 다시 가져오기"}
        </button>

        <p className="text-xs leading-relaxed text-muted">
          여기서 새로고침한 위치는 다음 추천·검색부터 바로 쓰여요. 브라우저가 위치 권한을 물으면
          허용해주세요.
        </p>
      </div>
    </main>
  );
}
