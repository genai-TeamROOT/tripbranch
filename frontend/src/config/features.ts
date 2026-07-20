/*
 * 역할: 프론트엔드 빌드 환경에서 사용하는 최소 feature flag를 제공한다.
 * 입력: VITE_ 접두사가 붙은 공개 환경변수.
 * 출력: 조건 해석 디버그 메시지 노출 여부.
 * 호출 시점: HomePage와 ChatPage가 모드별 흐름을 결정할 때 호출된다.
 * TODO: 서버 기반 feature flag가 필요해질 때만 별도 설정 계층으로 확장한다.
 */

export const featureFlags = {
  get showInterpretationDebug() {
    return import.meta.env.VITE_SHOW_INTERPRETATION_DEBUG === "true";
  },
};
