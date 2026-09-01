/*
 * 역할: "+" 버튼으로 고른 사진과 분위기가 닮은 장소를 찾아 대화에 붙인다.
 * 입력: 없음(TripContext에서 기기 위치를 읽는다).
 * 출력: ChatComposer의 onPhotoSelect에 그대로 넘길 수 있는 함수.
 * 호출 시점: ChatPage와 DeveloperChatPage가 입력창을 조립할 때.
 *
 * 두 화면이 같은 동작을 해야 해서 훅으로 뺐다 — 한쪽만 고치면 개발자 화면에서
 * 재현한 것이 사용자 화면과 달라진다.
 *
 * 위치는 대화가 이미 잡은 것을 먼저 쓴다 — 세션을 넘기면 서버가 B의 누적 조건에서
 * search_center → current_location 순으로 찾는다(기존 추천과 같은 순서). 대화가
 * 위치를 안 잡았을 때만 기기 GPS로 떨어지고, 둘 다 없으면 서버가 location_required로
 * 되묻는다. 사진 경로는 아직 되묻기 버튼 흐름을 타지 않으므로 오류 배너로 보여준다.
 */

import { useCallback } from "react";
import { ApiError } from "../api/client";
import { searchPlacesByPhoto } from "../api/trip";
import { useTripDispatch, useTripState } from "../state/TripContext";
import { createThumbnailDataUrl } from "../utils/imageThumbnail";

export function usePhotoSimilarSearch() {
  const state = useTripState();
  const dispatch = useTripDispatch();

  return useCallback(
    async (file: File) => {
      // "37.5788,126.9770" 형식이다. 값이 없거나 깨졌으면 좌표를 안 보낸다 —
      // NaN을 실어 보내면 서버가 좌표가 있는 줄 알고 되묻지 않는다.
      const [latitude, longitude] = (state.device_location ?? "")
        .split(",")
        .map((value) => Number(value.trim()));
      const hasCoordinates = Number.isFinite(latitude) && Number.isFinite(longitude);

      dispatch({ type: "CLEAR_ERROR" });

      // 사진을 먼저 띄운다. 응답이 1~2초라 아무것도 없으면 멈춘 것처럼 보인다.
      // 축소본을 만드는 데 실패해도(HEIC 등) 검색은 그대로 진행한다.
      const messageId = `photo-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const imageUrl = await createThumbnailDataUrl(file);
      dispatch({ type: "START_PHOTO_SIMILAR", payload: { messageId, imageUrl } });

      try {
        const response = await searchPlacesByPhoto({
          image: file,
          // 앞 턴에서 "안국역"이라고 말했으면 서버가 그 위치를 이어받는다.
          // 좌표는 대화가 위치를 안 잡았을 때의 기본값이다.
          sessionId: state.session_id,
          latitude: hasCoordinates ? latitude : null,
          longitude: hasCoordinates ? longitude : null,
          // 다섯 곳만 보여준다. 일반 추천과 개수를 맞추고, 무엇보다 **품질이
          // 아래로 갈수록 떨어진다** — 사람 눈가림 채점에서 상위 3곳과 5곳의
          // 성적 차이가 뚜렷했다. 서버 기본값은 10이라 이 줄이 없으면 재본 적
          // 없는 6~10위까지 화면에 실린다.
          limit: 5,
        });
        dispatch({
          type: "RESOLVE_PHOTO_SIMILAR",
          payload: {
            messageId,
            centerName: response.center_name,
            places: response.places,
            candidateCount: response.candidate_count,
            elapsedMs: response.elapsed_ms,
          },
        });
      } catch (error) {
        dispatch({ type: "FAIL_PHOTO_SIMILAR", payload: { messageId } });
        dispatch({
          type: "SET_ERROR",
          payload: error instanceof ApiError ? error.message : "사진으로 장소를 찾지 못했어요.",
        });
      }
    },
    [dispatch, state.device_location, state.session_id],
  );
}
