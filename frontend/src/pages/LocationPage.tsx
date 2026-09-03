/*
 * 역할: 위치 설정 화면. Figma "Location (Sheet)"(29:2) 화면 그대로 옮긴 것이다.
 * 입력: TripContext의 device_location, localStorage의 즐겨찾기, 검색어.
 * 출력: 장소 검색 결과 목록(GET /api/places/search — 서버가 서울 안으로 좁혀
 *   준다)과 그중 고른 검색 위치(SET_SEARCH_CENTER 디스패치 → 다음 요청부터
 *   AgentRequest.selected_search_center로 실려 간다), "현재 위치 사용"(실제
 *   브라우저 GPS 재조회 — SET_DEVICE_LOCATION 디스패치), 즐겨찾기 목록(사이드바와
 *   같은 저장소 공유). 최근 검색은 검색 기록을 아직 저장하지 않아 자리만 잡아 둔다.
 *
 * 검색 위치와 현재 위치는 다른 값이다. 검색 위치는 "어디를 기준으로 찾을지"이고
 * 현재 위치는 "사용자가 지금 있는 곳"이라, 이동시간 출발점과 위치 재확인은
 * 현재 위치만 본다. 그래서 고른 장소를 device_location에 넣지 않는다.
 * 호출 시점: 사이드바 "위치 설정"에서 바텀시트로 열린다(DESIGN_SYSTEM.md §5).
 */

import { Crosshair, Heart, Info, MapPin, Plus, Search, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
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
import { searchPlaces } from "../api/trip";
import type { PlaceSearchCandidate } from "../types";

export function LocationPage() {
  const navigate = useNavigate();
  const state = useTripState();
  const dispatch = useTripDispatch();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [favorites, setFavorites] = useState<FavoritePlace[]>(() => loadFavorites());
  const [showAddFavorite, setShowAddFavorite] = useState(false);
  const [query, setQuery] = useState("");
  /* null은 "아직 검색하지 않았다"이고 빈 배열은 "찾았는데 없었다"다. 둘을 하나로
     합치면 화면을 처음 열었을 때부터 "찾은 장소가 없어요"가 뜬다. */
  const [searchResults, setSearchResults] = useState<PlaceSearchCandidate[] | null>(null);
  const [outsideServiceAreaCount, setOutsideServiceAreaCount] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

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

  /* 입력할 때마다 부르지 않고 제출할 때만 부른다. Naver 지역 검색은 호출 한도가
     있는 유료 API라 글자마다 부르면 한 번 검색에 열 번 넘게 나간다. */
  function handleSelect(place: PlaceSearchCandidate) {
    /* 좌표가 아니라 이름을 넘긴다 — 이름을 좌표로 바꾸는 경로는 백엔드의
       ResolveLocationTool 하나로 이미 정리돼 있다(AgentRequest.
       selected_search_center 주석 참고). */
    dispatch({ type: "SET_SEARCH_CENTER", payload: { name: place.name } });
    setSearchResults(null);
    setQuery("");
  }

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || isSearching) return;
    setIsSearching(true);
    setSearchError(null);
    try {
      const response = await searchPlaces(trimmed);
      setSearchResults(response.places);
      setOutsideServiceAreaCount(response.outside_service_area_count);
    } catch (error) {
      setSearchResults(null);
      setSearchError(error instanceof Error ? error.message : "장소를 찾지 못했어요.");
    } finally {
      setIsSearching(false);
    }
  }

  return (
    <main className="flex h-full flex-col overflow-y-auto">
      <AppHeader onBack={() => navigate(-1)} />
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-3 px-4 pb-10">
        <form
          onSubmit={handleSearch}
          className="flex h-12 items-center gap-2 rounded-xl border border-border bg-white px-3.5 focus-within:border-brand"
        >
          <Search size={16} className="shrink-0 text-muted" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="장소 검색"
            placeholder="장소, 지하철역, 주소 검색"
            className="min-w-0 flex-1 bg-transparent text-base text-ink outline-none placeholder:text-muted"
          />
          <button
            type="submit"
            disabled={!query.trim() || isSearching}
            className="shrink-0 text-xs font-bold text-brand transition-opacity disabled:opacity-40"
          >
            {isSearching ? "검색 중" : "검색"}
          </button>
        </form>

        {state.selected_search_center && (
          <div className="flex items-center gap-2.5 rounded-xl bg-white px-3.5 py-3 shadow-resting">
            <MapPin size={17} className="shrink-0 text-brand" />
            <div className="min-w-0 flex-1">
              <p className="text-xs text-muted">이 위치를 기준으로 찾아요</p>
              <p className="truncate text-sm font-bold text-ink">
                {state.selected_search_center}
              </p>
            </div>
            <button
              type="button"
              onClick={() => dispatch({ type: "SET_SEARCH_CENTER", payload: { name: null } })}
              className="shrink-0 text-xs font-bold text-muted transition-colors hover:text-rust"
            >
              해제
            </button>
          </div>
        )}

        {searchError && (
          <p role="alert" className="px-1 text-xs text-rust">
            {searchError}
          </p>
        )}

        {searchResults !== null && (
          <div>
            <h2 className="mb-1 text-xs font-bold text-label">검색 결과</h2>
            <div className="divide-y divide-border border-t border-border">
              {searchResults.length === 0 ? (
                /* 서울 밖이라 걸러진 것과 아예 못 찾은 것은 다음에 할 일이
                   다르다 — 앞은 지역을 바꿔야 하고 뒤는 검색어를 고쳐야 한다. */
                <p className="py-3 text-sm text-muted">
                  {outsideServiceAreaCount > 0
                    ? "서울 지역만 검색할 수 있어요"
                    : "찾은 장소가 없어요"}
                </p>
              ) : (
                searchResults.map((place) => (
                  <button
                    type="button"
                    key={`${place.name}-${place.latitude},${place.longitude}`}
                    onClick={() => handleSelect(place)}
                    className="flex w-full items-start gap-2.5 py-3 text-left transition-opacity hover:opacity-60"
                  >
                    <MapPin size={15} className="mt-0.5 shrink-0 text-brand" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-bold text-ink">{place.name}</p>
                      <p className="truncate text-xs text-muted">
                        {place.road_address ?? place.address ?? ""}
                      </p>
                    </div>
                    {place.category && (
                      <span className="shrink-0 text-xs text-muted">{place.category}</span>
                    )}
                  </button>
                ))
              )}
            </div>
          </div>
        )}

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
          {/* 검색은 되지만 기록을 저장하지 않아 아직 비어 있다. */}
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
