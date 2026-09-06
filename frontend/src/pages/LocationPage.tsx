/*
 * 역할: 위치 설정 화면. Figma "Location (Sheet)"(29:2) 화면 그대로 옮긴 것이다.
 * 입력: TripContext의 device_location, localStorage의 즐겨찾기, 검색어.
 * 출력: 장소 검색 결과 목록(GET /api/places/search — 서버가 서울 안으로 좁혀
 *   준다)과 그중 고른 장소의 쓰임새(모달로 출발지·검색 기준을 갈라 물어
 *   locationSettings에 저장 → 다음 요청부터 AgentRequest.selected_current_location·
 *   selected_search_center로 실려 간다), "현재 위치 사용"(실제
 *   브라우저 GPS 재조회 — SET_DEVICE_LOCATION 디스패치), 즐겨찾기와 최근 고른
 *   장소 목록(눌러서 검색 위치로 잡는다).
 *
 * 즐겨찾기는 사이드바와 저장소를 공유한다 — 여기서 담은 장소가 사이드바 목록에도
 * 함께 보인다.
 *
 * 검색 위치와 현재 위치는 다른 값이다. 검색 위치는 "어디를 기준으로 찾을지"이고
 * 현재 위치는 "사용자가 지금 있는 곳"이라, 이동시간 출발점과 위치 재확인은
 * 현재 위치만 본다. 그래서 고른 장소를 device_location에 넣지 않는다.
 * 호출 시점: 사이드바 "위치 설정"에서 바텀시트로 열린다(DESIGN_SYSTEM.md §5).
 */

import {
  ArrowRight,
  Check,
  Crosshair,
  Info,
  MapPin,
  MapPinCheck,
  MapPinned,
  Navigation,
  Search,
  Star,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/layout/AppHeader";
import { FavoritesLimitModal } from "../components/layout/FavoritesLimitModal";
import { useTripDispatch, useTripState } from "../state/TripContext";
import { createId, type FavoritePlace } from "../state/sidebarStorage";
import { getLocationAgeMinutes } from "../utils/locationRefresh";
import { getBrowserDeviceLocation } from "../utils/geolocation";
import { setLocationCenter, setLocationOrigin } from "../state/locationSettings";
import {
  LocationPurposeModal,
  type LocationPurpose,
} from "../components/layout/LocationPurposeModal";
import { useFavorites } from "../hooks/useFavorites";
import { useLocationSettings } from "../hooks/useLocationSettings";
import { loadRecentSearches, rememberRecentSearch } from "../state/recentSearchesStorage";
import { searchPlaces } from "../api/trip";
import type { PlaceSearchCandidate } from "../types";

const MAX_FAVORITES = 10;

export function LocationPage() {
  const navigate = useNavigate();
  const state = useTripState();
  const dispatch = useTripDispatch();
  const isEn = state.language === "en";
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [favorites, setFavorites] = useFavorites();
  const [showFavoritesLimit, setShowFavoritesLimit] = useState(false);
  const [query, setQuery] = useState("");
  /* null은 "아직 검색하지 않았다"이고 빈 배열은 "찾았는데 없었다"다. 둘을 하나로
     합치면 화면을 처음 열었을 때부터 "찾은 장소가 없어요"가 뜬다. */
  const [searchResults, setSearchResults] = useState<PlaceSearchCandidate[] | null>(null);
  const [outsideServiceAreaCount, setOutsideServiceAreaCount] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  /* 저장소가 진실이고 이 state는 화면을 다시 그리기 위한 사본이다 — 발화를 보낼
     때는 HomePage·ChatPage가 저장소를 직접 읽는다. */
  const locationSettings = useLocationSettings();
  /* 고른 장소를 출발지로 쓸지 검색 기준으로 쓸지 아직 못 정한 상태. null이면
     모달이 닫혀 있다. */
  const [pendingPlace, setPendingPlace] = useState<string | null>(null);
  const [recentSearches, setRecentSearches] = useState<string[]>(() => loadRecentSearches());
  /* 이름을 고치는 중인 즐겨찾기. null이면 아무것도 고치고 있지 않다. */
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const searchBoxRef = useRef<HTMLDivElement>(null);


  const ageMinutes = getLocationAgeMinutes(state.device_location_captured_at);

  /* 결과 패널은 화면 위에 떠 있어서 스스로 닫히지 않는다. 바깥을 누르거나 Esc를
     누르면 닫는다 — 열어둔 채로 아래 즐겨찾기를 누르려다 가려지는 일이 없게. */
  useEffect(() => {
    if (searchResults === null) return;

    function handlePointerDown(event: MouseEvent) {
      if (!searchBoxRef.current?.contains(event.target as Node)) setSearchResults(null);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setSearchResults(null);
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [searchResults]);

  async function handleUseCurrentLocation() {
    if (isRefreshing) return;
    setIsRefreshing(true);
    setErrorMessage(null);
    try {
      const deviceLocation = await getBrowserDeviceLocation({ forceFresh: true, language: state.language });
      dispatch({
        type: "SET_DEVICE_LOCATION",
        payload: { deviceLocation, capturedAt: Date.now() },
      });
      /* 이 버튼의 뜻은 하나다 — "내 위치는 기기 좌표다". 그래서 쓰임새를 되묻지
         않고 출발지만 되돌린다. 검색 기준까지 비우려면 칩의 ✕로 따로 푼다. */
      setLocationOrigin(null);
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : isEn ? "Couldn't get your location." : "위치를 가져오지 못했어요.",
      );
    } finally {
      setIsRefreshing(false);
    }
  }

  /* 입력할 때마다 부르지 않고 제출할 때만 부른다. Naver 지역 검색은 호출 한도가
     있는 유료 API라 글자마다 부르면 한 번 검색에 열 번 넘게 나간다. */
  /* 모달에서 고른 쓰임새대로 저장한다. */
  function applyPurpose(purpose: LocationPurpose) {
    if (pendingPlace === null) return;
    if (purpose === "origin") setLocationOrigin(pendingPlace);
    else setLocationCenter(pendingPlace);
    setPendingPlace(null);
  }

  function handleSelect(place: PlaceSearchCandidate) {
    /* 좌표가 아니라 이름을 저장한다 — 이름을 좌표로 바꾸는 경로는 백엔드의
       ResolveLocationTool 하나로 이미 정리돼 있다(AgentRequest.
       selected_search_center 주석 참고). */
    setPendingPlace(place.name);
    setSearchResults(null);
    setQuery("");
  }

  function startRename(favoriteId: string, label: string) {
    setRenamingId(favoriteId);
    setRenameDraft(label);
  }

  /* 빈 이름은 저장하지 않는다 — 목록에서 어느 줄인지 알 수 없게 된다. 검색 위치로
     보내는 값(searchCenterName)은 건드리지 않으므로, 이름을 바꿔도 위치는 그대로다. */
  function commitRename() {
    const trimmed = renameDraft.trim();
    if (trimmed) {
      setFavorites((prev) =>
        prev.map((favorite) =>
          favorite.id === renamingId ? { ...favorite, label: trimmed } : favorite,
        ),
      );
    }
    setRenamingId(null);
  }

  /* 같은 즐겨찾기가 출발지일 수도 검색 기준일 수도 있어, 하나로 뭉치면 목록에서
     어느 쪽인지 알 수 없다. 역할을 그대로 돌려준다. */
  function favoriteRole(favorite: FavoritePlace): "origin" | "center" | null {
    const name = favorite.searchCenterName ?? favorite.label;
    if (locationSettings.center === name) return "center";
    if (locationSettings.origin === name) return "origin";
    return null;
  }

  function favoriteLabel(favorite: FavoritePlace) {
    const role = favoriteRole(favorite);
    if (isEn) {
      if (role === "center") return `${favorite.label} is the current search center`;
      if (role === "origin") return `${favorite.label} is the current starting point`;
      return `Set ${favorite.label} as search location`;
    }
    if (role === "center") return `${favorite.label}이 지금 검색 기준이에요`;
    if (role === "origin") return `${favorite.label}이 지금 출발지예요`;
    return `${favorite.label}을 검색 위치로 설정`;
  }

  function isFavorite(place: PlaceSearchCandidate) {
    return favorites.some(
      (favorite) => (favorite.searchCenterName ?? favorite.label) === place.name,
    );
  }

  /* 같은 곳을 두 번 담아 줄이 두 개 생기지 않게, 이미 있으면 뺀다(누르면 토글). */
  function toggleFavorite(place: PlaceSearchCandidate) {
    if (!isFavorite(place) && favorites.length >= MAX_FAVORITES) {
      setShowFavoritesLimit(true);
      return;
    }
    setFavorites((prev) =>
      isFavorite(place)
        ? prev.filter((favorite) => (favorite.searchCenterName ?? favorite.label) !== place.name)
        : [
            ...prev,
            {
              id: createId("fav"),
              label: place.name,
              searchCenterName: place.name,
              address: place.road_address ?? place.address,
            },
          ],
    );
  }

  async function handleSearch(event: FormEvent) {
    event.preventDefault();
    await runSearch(query);
  }

  async function runSearch(rawQuery: string) {
    const trimmed = rawQuery.trim();
    if (!trimmed || isSearching) return;
    setQuery(trimmed);
    setIsSearching(true);
    setSearchError(null);
    /* 결과가 오기 전에 남긴다 — 못 찾은 검색어야말로 다시 꺼내 고쳐 쓰게 된다. */
    setRecentSearches(rememberRecentSearch(trimmed));
    try {
      const response = await searchPlaces(trimmed);
      setSearchResults(response.places);
      setOutsideServiceAreaCount(response.outside_service_area_count);
    } catch (error) {
      setSearchResults(null);
      setSearchError(
        error instanceof Error ? error.message : isEn ? "Couldn't find the place." : "장소를 찾지 못했어요.",
      );
    } finally {
      setIsSearching(false);
    }
  }

  return (
    <main className="flex h-full flex-col overflow-y-auto">
      <AppHeader onBack={() => navigate(-1)} />
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-3 px-4 pb-10">
        {/* 결과를 문서 흐름에 두면 아래 카드들이 통째로 밀려 내려간다. 검색창을
            기준으로 띄워서 화면이 그대로 있게 한다. */}
        <div ref={searchBoxRef} className="relative">
          <form
            onSubmit={handleSearch}
            className="flex h-12 items-center gap-2 rounded-xl border border-border bg-white px-3.5 focus-within:border-brand"
          >
            <Search size={16} className="shrink-0 text-muted" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label={isEn ? "Search places" : "장소 검색"}
              placeholder={isEn ? "Search places, subway stations, addresses" : "장소, 지하철역, 주소 검색"}
              className="min-w-0 flex-1 bg-transparent text-base text-ink outline-none placeholder:text-muted"
            />
            <button
              type="submit"
              disabled={!query.trim() || isSearching}
              className="shrink-0 text-xs font-bold text-brand transition-opacity disabled:opacity-40"
            >
              {isEn ? (isSearching ? "Searching" : "Search") : isSearching ? "검색 중" : "검색"}
            </button>
          </form>

          {searchResults !== null && (
            <div className="absolute inset-x-0 top-full z-20 mt-1 max-h-80 overflow-y-auto rounded-xl border border-border bg-white px-3.5 shadow-card">
              <h2 className="sr-only">{isEn ? "Search results" : "검색 결과"}</h2>
              <div className="divide-y divide-border">
                {searchResults.length === 0 ? (
                  /* 서울 밖이라 걸러진 것과 아예 못 찾은 것은 다음에 할 일이
                   다르다 — 앞은 지역을 바꿔야 하고 뒤는 검색어를 고쳐야 한다. */
                  <p className="py-3 text-sm text-muted">
                    {isEn
                      ? outsideServiceAreaCount > 0
                        ? "We can only search within Seoul"
                        : "No places found"
                      : outsideServiceAreaCount > 0
                        ? "서울 지역만 검색할 수 있어요"
                        : "찾은 장소가 없어요"}
                  </p>
                ) : (
                  searchResults.map((place) => (
                    <div
                      key={`${place.name}-${place.latitude},${place.longitude}`}
                      className="-mx-3.5 flex items-start gap-2.5 px-3.5 py-3 transition-colors hover:bg-chip"
                    >
                      <button
                        type="button"
                        aria-label={isEn ? `Set ${place.name} as search location` : `${place.name} 검색 위치로 설정`}
                        onClick={() => handleSelect(place)}
                        className="flex min-w-0 flex-1 items-start gap-2.5 text-left"
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
                      <button
                        type="button"
                        aria-label={
                          isEn
                            ? isFavorite(place)
                              ? `Remove ${place.name} from favorites`
                              : `Add ${place.name} to favorites`
                            : isFavorite(place)
                              ? `${place.name} 즐겨찾기 해제`
                              : `${place.name} 즐겨찾기 추가`
                        }
                        aria-pressed={isFavorite(place)}
                        onClick={() => toggleFavorite(place)}
                        /* 한도가 차면 흐리게만 두고 disabled로 막지 않는다 — 눌러야
                           왜 안 담기는지 모달로 말할 수 있다. aria-disabled도 붙이지
                           않는다. 누르면 답이 오는 버튼을 "아무 일도 안 함"으로
                           읽히게 하는 표시라서다. */
                        className={`mt-0.5 shrink-0 transition-colors ${
                          !isFavorite(place) && favorites.length >= MAX_FAVORITES
                            ? "text-border"
                            : "text-muted hover:text-gold"
                        }`}
                      >
                        <Star
                          size={15}
                          className={isFavorite(place) ? "fill-gold text-gold" : undefined}
                        />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        {searchError && (
          <p role="alert" className="px-1 text-xs text-rust">
            {searchError}
          </p>
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
            {isEn
              ? isRefreshing
                ? "Getting your location…"
                : "Use current location"
              : isRefreshing
                ? "위치를 가져오는 중이에요…"
                : "현재 위치 사용"}
          </span>
        </button>
        {/* 지금 정해져 있는 두 값. 서로 다른 질문의 답이라 칩을 따로 두되, 사이에
            화살표를 넣어 "여기서 출발해 저기 주변을 찾는다"는 관계를 보인다.

            줄바꿈하지 않는다 — 칩이 아래로 내려가면 화살표만 줄 끝에 남는다. 대신
            칩은 제 내용만큼만 차지하고, 한 줄에 정말 안 들어갈 때만 이름을 자른다.
            반씩 나눠 가지면 "현재 위치에서 출발"처럼 짧은 쪽이 남는 자리를 붙들고
            있어서, 긴 이름 쪽이 자리가 있는데도 먼저 잘린다. */}
        <div className="flex items-center gap-2">
          <span className="flex min-w-0 items-center gap-1.5 rounded-full bg-chip px-3 py-1.5 text-xs text-ink">
            <Navigation size={13} className="shrink-0 text-brand" aria-hidden />
            <span className="truncate">
              {isEn
                ? `From ${locationSettings.origin ?? "current location"}`
                : `${locationSettings.origin ?? "현재 위치"}에서 출발`}
            </span>
            {locationSettings.origin && (
              <button
                type="button"
                aria-label={isEn ? "Reset starting point to current location" : "출발지를 현재 위치로 되돌리기"}
                onClick={() => setLocationOrigin(null)}
                className="shrink-0 text-muted transition-colors hover:text-rust"
              >
                <X size={12} />
              </button>
            )}
          </span>
          <ArrowRight size={14} aria-hidden className="shrink-0 text-muted" />
          <span className="flex min-w-0 items-center gap-1.5 rounded-full bg-chip px-3 py-1.5 text-xs text-ink">
            {/* 핀이 아니라 바닥 원이 깔린 핀이다 — 이 칩은 "그 지점"이 아니라
                "그 자리 주변"을 뒤진다는 뜻이라서다. */}
            <MapPinned size={13} className="shrink-0 text-brand" aria-hidden />
            {/* 비어 있다고 기준이 없는 게 아니다 — 그때는 출발지가, 출발지도 없으면
                기기 좌표가 검색 기준이 된다(agent_context/service.py). 그래서 실제로
                어디를 뒤지는지를 그대로 쓴다. */}
            <span className="truncate">
              {isEn
                ? `Search around ${locationSettings.center ?? locationSettings.origin ?? "current location"}`
                : `${locationSettings.center ?? locationSettings.origin ?? "현재 위치"} 주변에서 검색`}
            </span>
            {locationSettings.center && (
              <button
                type="button"
                aria-label={isEn ? "Reset search center" : "검색 기준 되돌리기"}
                onClick={() => setLocationCenter(null)}
                className="shrink-0 text-muted transition-colors hover:text-rust"
              >
                <X size={12} />
              </button>
            )}
          </span>
        </div>

        {state.device_location && (
          /* 좌표를 그대로 보여주면 사용자에게는 숫자 두 개일 뿐이다. 주소로 바꾸는
             역지오코딩은 아직 없으므로 "현재 위치"라고만 말한다. */
          <p className="px-1 text-xs text-muted">
            {isEn ? "Current location" : "현재 위치"}
            {ageMinutes === null
              ? ""
              : isEn
                ? ` · checked ${ageMinutes} min ago`
                : ` · ${ageMinutes}분 전에 확인했어요`}
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
            {isEn ? "We currently only recommend places in Seoul" : "현재 서울 지역 장소만 추천해 드리고 있어요"}
          </p>
        </div>

        <div className="mt-2 flex items-center justify-between">
          <h2 className="text-xs font-bold text-label">{isEn ? "Favorites" : "즐겨찾기"}</h2>
          <span className="text-xs font-bold text-muted">
            {favorites.length}/{MAX_FAVORITES}
          </span>
        </div>
        <div className="divide-y divide-border border-t border-border">
          {favorites.length === 0 ? (
            <p className="py-3 text-sm text-muted">
              {isEn ? "No favorites yet" : "등록된 즐겨찾기가 없어요"}
            </p>
          ) : (
            favorites.map((favorite) => (
              /* 줄 전체가 "이 장소를 쓰겠다"는 버튼이다 — 글자는 이름 바꾸기,
                 휴지통은 삭제라 각자 제 일이 있고, 그 사이 빈 자리를 눌러 고른다.
                 핀은 지금 기준으로 잡혀 있는지만 보여주는 표시로 남는다. */
              <div
                key={favorite.id}
                role="button"
                tabIndex={0}
                aria-label={favoriteLabel(favorite)}
                aria-pressed={favoriteRole(favorite) !== null}
                onClick={() => setPendingPlace(favorite.searchCenterName ?? favorite.label)}
                onKeyDown={(event) => {
                  /* 줄 자체에 포커스가 있을 때만 연다. 이 줄 안에는 이름 입력창과
                     버튼이 있어서, 안 걸러내면 이름을 고치다 스페이스만 눌러도
                     모달이 뜬다. */
                  if (event.target !== event.currentTarget) return;
                  if (event.key !== "Enter" && event.key !== " ") return;
                  event.preventDefault();
                  setPendingPlace(favorite.searchCenterName ?? favorite.label);
                }}
                className="-mx-4 flex cursor-pointer items-center gap-2.5 px-4 py-3 transition-colors hover:bg-chip"
              >
                <span
                  aria-hidden
                  className={`shrink-0 ${favoriteRole(favorite) ? "text-brand" : "text-muted"}`}
                >
                  {favoriteRole(favorite) === "origin" ? (
                    <Navigation size={16} />
                  ) : favoriteRole(favorite) === "center" ? (
                    <MapPinCheck size={16} />
                  ) : (
                    <MapPin size={16} />
                  )}
                </span>
                {renamingId === favorite.id ? (
                  <input
                    autoFocus
                    value={renameDraft}
                    aria-label={isEn ? `Rename ${favorite.label}` : `${favorite.label} 이름 바꾸기`}
                    onChange={(event) => setRenameDraft(event.target.value)}
                    onClick={(event) => event.stopPropagation()}
                    onBlur={commitRename}
                    onKeyDown={(event) => {
                      /* 줄 전체가 버튼이라 여기서 끊지 않으면 키가 위로 올라간다. */
                      event.stopPropagation();
                      if (event.key === "Enter") commitRename();
                      if (event.key === "Escape") setRenamingId(null);
                    }}
                    className="min-w-0 flex-1 rounded-lg border border-brand px-2 py-1 text-sm text-ink outline-none"
                  />
                ) : (
                  <button
                    type="button"
                    aria-label={isEn ? `Rename ${favorite.label}` : `${favorite.label} 이름 바꾸기`}
                    onClick={(event) => {
                      event.stopPropagation();
                      startRename(favorite.id, favorite.label);
                    }}
                    className="min-w-0 shrink text-left"
                  >
                    <span className="block truncate text-sm text-ink">{favorite.label}</span>
                    {favorite.address && (
                      <span className="block truncate text-xs text-muted">{favorite.address}</span>
                    )}
                  </button>
                )}
                {/* 남는 가로. 글자에 닿지 않고 줄을 누를 수 있는 자리다 — 이름
                    버튼이 flex-1로 가로를 다 먹으면 어디를 눌러도 이름 편집이 된다. */}
                <span aria-hidden className="min-h-6 flex-1 self-stretch" />
                {renamingId === favorite.id ? (
                  <button
                    type="button"
                    aria-label={isEn ? "Save name" : "이름 저장"}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={(event) => {
                      event.stopPropagation();
                      commitRename();
                    }}
                    className="shrink-0 text-brand"
                  >
                    <Check size={15} />
                  </button>
                ) : (
                  <button
                    type="button"
                    aria-label={isEn ? `Delete ${favorite.label} from favorites` : `${favorite.label} 즐겨찾기 삭제`}
                    onClick={(event) => {
                      event.stopPropagation();
                      setFavorites((prev) => prev.filter((item) => item.id !== favorite.id));
                    }}
                    className="shrink-0 text-muted transition-colors hover:text-rust"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            ))
          )}
        </div>

        <h2 className="mt-2 text-xs font-bold text-label">{isEn ? "Recent searches" : "최근 검색"}</h2>
        <div className="divide-y divide-border border-t border-border">
          {recentSearches.length === 0 ? (
            <p className="py-3 text-sm text-muted">
              {isEn ? "No searches yet" : "아직 검색한 장소가 없어요"}
            </p>
          ) : (
            recentSearches.map((keyword) => (
              <button
                type="button"
                key={keyword}
                onClick={() => void runSearch(keyword)}
                className="-mx-4 flex w-full items-center gap-2.5 px-4 py-3 text-left transition-colors hover:bg-chip"
              >
                <Search size={14} className="shrink-0 text-muted" />
                <span className="min-w-0 flex-1 truncate text-sm text-ink">{keyword}</span>
              </button>
            ))
          )}
        </div>
      </div>

      {pendingPlace !== null && (
        <LocationPurposeModal
          placeName={pendingPlace}
          onPick={applyPurpose}
          onClose={() => setPendingPlace(null)}
        />
      )}

      {showFavoritesLimit && (
        <FavoritesLimitModal max={MAX_FAVORITES} onClose={() => setShowFavoritesLimit(false)} />
      )}
    </main>
  );
}
