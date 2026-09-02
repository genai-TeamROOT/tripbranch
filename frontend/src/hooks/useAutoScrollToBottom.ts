/*
 * 역할: 스트리밍 중 새로 들어오는 답변을 따라 대화창을 부드럽게 바닥으로 붙인다.
 * 입력: 내용이 자라는 컨테이너의 ref, 지금 스트리밍 중인지(active).
 * 출력: 없음(부수효과로 스크롤만 옮긴다).
 * 호출 시점: ChatPage가 메시지 목록을 감싼 div에 붙인다.
 *
 * 실제로 스크롤되는 요소는 이 컨테이너의 부모가 아니라, overflow-y가 걸린
 * 가장 가까운 조상이다(페이지마다 그 조상이 다르다 — 자기 <main>일 수도,
 * 더 위의 .tb-shell일 수도 있다. 특정 클래스명에 기대지 않고 computed style로
 * 직접 찾는다). ChatMessageList가 답변을 한 글자씩 보여주는 타자기 효과(내부
 * setInterval)는 TripContext 상태 변화 없이 레이아웃만 자라므로, React 렌더
 * 이벤트로는 못 잡는다 — ResizeObserver로 실제 높이 변화를 직접 관찰한다.
 */

import { useEffect, useRef } from "react";

const NEAR_BOTTOM_THRESHOLD_PX = 80;

export function findScrollableAncestor(element: HTMLElement | null): HTMLElement | null {
  let node = element?.parentElement ?? null;
  while (node) {
    const overflowY = getComputedStyle(node).overflowY;
    if (overflowY === "auto" || overflowY === "scroll") return node;
    node = node.parentElement;
  }
  return null;
}

export function smoothScrollTo(scroller: HTMLElement, top: number) {
  if (typeof scroller.scrollTo === "function") {
    scroller.scrollTo({ top, behavior: "smooth" });
    return;
  }
  scroller.scrollTop = top;
}

export function useAutoScrollToBottom(
  containerRef: React.RefObject<HTMLElement | null>,
  active: boolean,
) {
  // 사용자가 위로 스크롤해 이전 메시지를 읽고 있으면, 스트리밍 중이라도
  // 억지로 바닥까지 끌어내리지 않는다.
  const shouldFollowRef = useRef(true);

  useEffect(() => {
    const scroller = findScrollableAncestor(containerRef.current);
    if (!scroller) return;

    const handleScroll = () => {
      const distanceFromBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      shouldFollowRef.current = distanceFromBottom <= NEAR_BOTTOM_THRESHOLD_PX;
    };
    scroller.addEventListener("scroll", handleScroll, { passive: true });
    return () => scroller.removeEventListener("scroll", handleScroll);
  }, [containerRef]);

  useEffect(() => {
    const container = containerRef.current;
    const scroller = findScrollableAncestor(container);
    if (!container || !scroller || !active) return;

    // 새 턴이 시작되는 시점에는 항상 바닥부터 다시 따라간다.
    shouldFollowRef.current = true;

    const observer = new ResizeObserver(() => {
      if (!shouldFollowRef.current) return;
      smoothScrollTo(scroller, scroller.scrollHeight);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [containerRef, active]);
}
