/*
 * 역할: 채팅 화면의 "맨 위/맨 아래로" 토글 버튼에 필요한 상태와 동작을 만든다.
 * 입력: 내용이 자라는 컨테이너의 ref(useAutoScrollToBottom과 같은 컨테이너를 준다).
 * 출력: 지금 맨 위 근처인지(isNearTop), 스크롤할 내용이 있는지(isScrollable),
 *   맨 위/맨 아래로 부드럽게 이동하는 함수.
 * 호출 시점: ChatPage가 컴포저 위 토글 버튼에 붙인다.
 */

import { useEffect, useState } from "react";
import { findScrollableAncestor, smoothScrollTo } from "./useAutoScrollToBottom";

const NEAR_TOP_THRESHOLD_PX = 80;

export function useScrollEdgeButton(containerRef: React.RefObject<HTMLElement | null>) {
  const [state, setState] = useState({ isNearTop: true, isScrollable: false });

  useEffect(() => {
    const container = containerRef.current;
    const scroller = findScrollableAncestor(container);
    if (!container || !scroller) return;

    const update = () => {
      setState({
        isNearTop: scroller.scrollTop <= NEAR_TOP_THRESHOLD_PX,
        isScrollable: scroller.scrollHeight > scroller.clientHeight + NEAR_TOP_THRESHOLD_PX,
      });
    };
    update();
    scroller.addEventListener("scroll", update, { passive: true });
    // 메시지가 새로 쌓이거나 스트리밍으로 길어지면 스크롤 가능 여부 자체가
    // 바뀐다 — scroll 이벤트만으로는 안 잡힌다.
    const observer = new ResizeObserver(update);
    observer.observe(container);
    return () => {
      scroller.removeEventListener("scroll", update);
      observer.disconnect();
    };
  }, [containerRef]);

  return {
    isNearTop: state.isNearTop,
    isScrollable: state.isScrollable,
    scrollToTop: () => {
      const scroller = findScrollableAncestor(containerRef.current);
      if (scroller) smoothScrollTo(scroller, 0);
    },
    scrollToBottom: () => {
      const scroller = findScrollableAncestor(containerRef.current);
      if (scroller) smoothScrollTo(scroller, scroller.scrollHeight);
    },
  };
}
