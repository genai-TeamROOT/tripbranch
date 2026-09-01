/*
 * 역할: 위치 설정 화면. Figma "Location (Sheet)"(29:2) 화면 그대로 옮긴 것이다.
 * 입력: TripContext의 device_location, localStorage의 즐겨찾기.
 * 출력: "현재 위치 사용"(실제 브라우저 GPS 재조회 — SET_DEVICE_LOCATION
 *   디스패치), 즐겨찾기 목록(사이드바와 같은 저장소 공유), 검색·최근 검색은
 *   장소 검색 기능 자체가 없어 자리만 잡아 둔다.
 * 호출 시점: 사이드바 "위치 설정"에서 바텀시트로 열린다(DESIGN_SYSTEM.md §5).
 */

import { Crosshair, Heart, Info, Plus, Search, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/layout/AppHeader";
import { AddFavoriteModal } from "../components/layout/AddFavoriteModal";
import { useTripDispatch, useTripState } from "../state/TripContext";
import {
  createId,
  loadFavorites,
  saveFavorites,
  type FavoritePlace,
} from "../state/sidebarStorage";
import { getLocationAgeMinutes } from "../utils/locationRefresh";
import { getBrowserDeviceLocation } from "../utils/geolocation";

export function LocationPage() {
  const navigate = useNavigate();
  const state = useTripState();
  const dispatch = useTripDispatch();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [favorites, setFavorites] = useState<FavoritePlace[]>(() => loadFavorites());
  const [showAddFavorite, setShowAddFavorite] = useState(false);

  useEffect(() => saveFavorites(favorites), [favorites]);

  const ageMinutes = getLocationAgeMinutes(state.device_location_captured_at);

  async function handleUseCurrentLocation() {
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
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-3 px-4 pb-10">
        {/* 장소 검색은 아직 없다 — 자리만 잡아 둔 자리표시 입력(§10.6). */}
        <div className="flex h-12 items-center gap-2 rounded-xl border border-border bg-white px-3.5">
          <Search size={16} className="shrink-0 text-muted" />
          <span className="truncate text-base text-muted">장소, 지하철역, 주소 검색</span>
        </div>

        <button
          type="button"
          disabled={isRefreshing}
          onClick={() => void handleUseCurrentLocation()}
          className="flex items-center gap-2.5 rounded-xl bg-white px-3.5 py-3 text-left shadow-resting transition-opacity disabled:opacity-50"
        >
          <Crosshair
            size={17}
            className={`shrink-0 text-brand ${isRefreshing ? "animate-pulse" : ""}`}
          />
          <span className="text-sm font-bold text-brand">
            {isRefreshing ? "위치를 가져오는 중이에요…" : "현재 위치 사용"}
          </span>
        </button>
        {state.device_location && (
          <p className="px-1 text-xs text-muted">
            {state.device_location}
            {ageMinutes === null ? "" : ` · ${ageMinutes}분 전에 확인했어요`}
          </p>
        )}
        {errorMessage && (
          <p role="alert" className="px-1 text-xs text-rust">
            {errorMessage}
          </p>
        )}

        <div className="flex items-start gap-2 rounded-xl bg-sky-light px-3.5 py-2.5">
          <Info size={14} className="mt-0.5 shrink-0 text-brand-deep" />
          <p className="text-xs leading-relaxed text-brand-deep">
            현재 서울 지역 장소만 추천해 드리고 있어요
          </p>
        </div>

        <div className="mt-2 flex items-center justify-between">
          <h2 className="text-xs font-bold text-label">즐겨찾기</h2>
          <button
            type="button"
            onClick={() => setShowAddFavorite(true)}
            className="flex items-center gap-1 text-xs font-bold text-brand"
          >
            <Plus size={13} /> 추가
          </button>
        </div>
        <div className="divide-y divide-border border-t border-border">
          {favorites.length === 0 ? (
            <p className="py-3 text-sm text-muted">등록된 즐겨찾기가 없어요</p>
          ) : (
            favorites.map((favorite) => (
              <div key={favorite.id} className="flex items-center gap-2.5 py-3">
                <Heart size={15} className="shrink-0 text-gold" />
                <span className="min-w-0 flex-1 truncate text-sm text-ink">{favorite.label}</span>
                <button
                  type="button"
                  aria-label={`${favorite.label} 즐겨찾기 삭제`}
                  onClick={() =>
                    setFavorites((prev) => prev.filter((item) => item.id !== favorite.id))
                  }
                  className="shrink-0 text-muted transition-colors hover:text-rust"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))
          )}
        </div>

        <h2 className="mt-2 text-xs font-bold text-label">최근 검색</h2>
        <div className="border-t border-border">
          {/* 장소 검색 기능이 없어 최근 검색 기록도 아직 없다. */}
          <p className="py-3 text-sm text-muted">아직 검색한 장소가 없어요</p>
        </div>
      </div>

      {showAddFavorite && (
        <AddFavoriteModal
          onAdd={(label) => setFavorites((prev) => [...prev, { id: createId("fav"), label }])}
          onClose={() => setShowAddFavorite(false)}
        />
      )}
    </main>
  );
}
