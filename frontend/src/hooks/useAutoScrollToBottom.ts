/*
 * 역할: 스트리밍 중 새로 들어오는 답변을 따라 대화창을 계속 바닥에 붙인다.
 * 입력: 내용이 자라는 컨테이너의 ref, 지금 스트리밍 중인지(active).
 * 출력: 없음(부수효과로 스크롤만 옮긴다).
 * 호출 시점: ChatPage가 메시지 목록을 감싼 div에 붙인다.
 *
 * 실제로 스크롤되는 요소는 이 컨테이너가 아니라 .tb-shell이다(AppShell 참고 —
 * 페이지 자신은 overflow를 안 걸고 tb-shell이 전체를 스크롤한다). ChatMessageList가
 * 답변을 한 글자씩 보여주는 타자기 효과(내부 setInterval)는 TripContext 상태
 * 변화 없이 레이아웃만 자라므로, React 렌더 이벤트로는 못 잡는다 — ResizeObserver로
 * 실제 높이 변화를 직접 관찰한다.
 */

import { useEffect, useRef } from "react";

const NEAR_BOTTOM_THRESHOLD_PX = 80;

export function useAutoScrollToBottom(
  containerRef: React.RefObject<HTMLElement | null>,
  active: boolean,
) {
  // 사용자가 위로 스크롤해 이전 메시지를 읽고 있으면, 스트리밍 중이라도
  // 억지로 바닥까지 끌어내리지 않는다.
  const shouldFollowRef = useRef(true);

  useEffect(() => {
    const shell = containerRef.current?.closest<HTMLElement>(".tb-shell");
    if (!shell) return;

    const handleScroll = () => {
      const distanceFromBottom = shell.scrollHeight - shell.scrollTop - shell.clientHeight;
      shouldFollowRef.current = distanceFromBottom <= NEAR_BOTTOM_THRESHOLD_PX;
    };
    shell.addEventListener("scroll", handleScroll, { passive: true });
    return () => shell.removeEventListener("scroll", handleScroll);
  }, [containerRef]);

  useEffect(() => {
    const container = containerRef.current;
    const shell = container?.closest<HTMLElement>(".tb-shell");
    if (!container || !shell || !active) return;

    // 새 턴이 시작되는 시점에는 항상 바닥부터 다시 따라간다.
    shouldFollowRef.current = true;

    const observer = new ResizeObserver(() => {
      if (!shouldFollowRef.current) return;
      shell.scrollTop = shell.scrollHeight;
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [containerRef, active]);
}
