/*
 * 역할: 화면에 실제로 보이는 높이(visualViewport)를 추적한다.
 * 입력: 없음 — `window.visualViewport`를 직접 구독한다.
 * 출력: 무언가 화면을 가려 실제 보이는 높이가 줄어든 동안의 px 값. 평소·미지원
 *   환경에서는 null이다.
 * 호출 시점: 모바일 소프트 키보드가 뜰 때 레이아웃을 맞춰야 하는 화면(ChatPage)이 쓴다.
 *
 * **레이아웃 뷰포트(`100dvh`)는 키보드를 계산에 안 넣는다.** 동적 뷰포트 단위는
 * 주소창처럼 브라우저 자체 UI가 늘고 주는 것만 반영하고, 소프트 키보드는 별개다.
 * 그래서 입력칸에 포커스가 가면 브라우저가 "포커스된 요소를 보이게" 문서를
 * 스크롤하는데, 이 앱에서 그 스크롤 대상은 헤더까지 포함한 화면 전체(가장 가까운
 * overflow-y:auto 조상)라 헤더까지 함께 밀려 올라가 보였다(2026-09-07 실측).
 *
 * 스크롤 대신 **박스 자체를 줄이면** 그 안의 flex 레이아웃(헤더 고정 + 메시지
 * flex-1 + 입력창 하단)이 알아서 재배치되어 스크롤이 필요 없어진다 — 이 값을
 * 그 박스의 height로 직접 먹인다.
 */

import { useEffect, useState } from "react";

export function useVisualViewportHeight(): number | null {
  const [height, setHeight] = useState<number | null>(null);

  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;

    function update() {
      /* window.innerHeight(레이아웃 뷰포트)보다 실제로 보이는 영역이 작을
         때만 값을 낸다 — 키보드 같은 것이 진짜로 가리고 있을 때만 개입하고,
         평소에는 CSS(100dvh)를 그대로 믿는다. */
      setHeight(viewport!.height < window.innerHeight ? viewport!.height : null);
    }

    update();
    viewport.addEventListener("resize", update);
    return () => viewport.removeEventListener("resize", update);
  }, []);

  return height;
}
