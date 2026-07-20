/*
 * 역할: ChatPage 하단에서 후속 사용자 입력을 받는다.
 * 입력: 텍스트 입력, 요청 중 여부, 제출 콜백.
 * 출력: 채팅 입력 form.
 * 호출 시점: ChatPage가 대화 하단 입력창을 렌더링할 때 호출된다.
 * TODO: 실제 다회 대화 의미 분석이 생기면 입력 종류와 컨텍스트 전달을 확장한다.
 */

import { useState, type FormEvent } from "react";

interface ChatComposerProps {
  disabled: boolean;
  onSubmit: (text: string) => Promise<void>;
}

export function ChatComposer({ disabled, onSubmit }: ChatComposerProps) {
  const [text, setText] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextText = text.trim();
    if (!nextText || disabled) return;
    setText("");
    await onSubmit(nextText);
  }

  return (
    <form onSubmit={handleSubmit} className="sticky bottom-0 flex gap-2 bg-white py-4 dark:bg-gray-950">
      <input
        value={text}
        onChange={(event) => setText(event.target.value)}
        disabled={disabled}
        placeholder="추가 조건을 입력해 주세요"
        className="min-w-0 flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none disabled:opacity-50 dark:border-gray-700 dark:bg-gray-900"
      />
      <button
        type="submit"
        disabled={disabled || !text.trim()}
        className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
      >
        보내기
      </button>
    </form>
  );
}
