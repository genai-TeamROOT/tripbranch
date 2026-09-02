/*
 * 역할: 지금 진행 중인 채팅 스트리밍 요청 하나를 앱 전체에서 공유한다.
 * 입력: 없음(모듈 싱글턴).
 * 출력: 새 요청 시작 시 발급하는 AbortController, 중단 요청.
 * 호출 시점: HomePage 첫 발화·ChatPage 후속 발화가 streamChat을 부를 때, 그리고
 *   ChatComposer의 "중단" 버튼이 눌렸을 때(DESIGN_SYSTEM.md §7.2).
 *
 * HomePage는 발화를 보내자마자 /chat으로 이동한다(HomePage.tsx) — 실제 요청은
 * HomePage가 언마운트된 뒤에도 그 클로저 안에서 계속 진행된다. 컴포넌트 인스턴스
 * 마다 컨트롤러를 들고 있으면 ChatPage의 중단 버튼이 그 요청에 닿을 수 없다.
 * "지금 이 앱에 걸린 채팅 요청은 한 번에 하나뿐"이라는 실제 제약을 그대로
 * 모듈 싱글턴으로 표현한다.
 */

let currentController: AbortController | null = null;

/** 새 채팅 요청을 시작할 때 부른다. 남아 있던 이전 요청이 있으면 먼저 정리한다. */
export function beginChatRequest(): AbortController {
  currentController?.abort();
  const controller = new AbortController();
  currentController = controller;
  return controller;
}

/** 요청이 끝났을 때(성공·실패·취소 모두) 부른다. 다른 요청이 이미 시작됐으면 건드리지 않는다. */
export function endChatRequest(controller: AbortController): void {
  if (currentController === controller) currentController = null;
}

/** ChatComposer의 "중단" 버튼이 부른다. */
export function cancelChatRequest(): void {
  currentController?.abort();
}
