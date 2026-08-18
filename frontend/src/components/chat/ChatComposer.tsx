/*
 * 역할: ChatPage 하단에서 후속 사용자 입력을 받는다.
 * 입력: 텍스트 입력, 요청 중 여부, 제출 콜백, 상황별 placeholder.
 * 출력: 채팅 입력 form.
 * 호출 시점: ChatPage가 대화 하단 입력창을 렌더링할 때 호출된다.
 * TODO: 실제 다회 대화 의미 분석이 생기면 입력 종류와 컨텍스트 전달을 확장한다.
 */

import { useState, type FormEvent } from "react";
import { VoiceInputButton } from "./VoiceInputButton";

const DEFAULT_PLACEHOLDER = "추가 조건을 입력해 주세요";

interface ChatComposerProps {
  disabled: boolean;
  onSubmit: (text: string) => Promise<void>;
  /* 되묻기처럼 특정 형태의 답변이 필요할 때 예시 문장을 안내한다. */
  placeholder?: string;
}

export function ChatComposer({
  disabled,
  onSubmit,
  placeholder = DEFAULT_PLACEHOLDER,
}: ChatComposerProps) {
  const [text, setText] = useState("");
  const [voiceError, setVoiceError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextText = text.trim();
    if (!nextText || disabled) return;
    setText("");
    await onSubmit(nextText);
  }

  return (
    <div className="sticky bottom-0 bg-white py-4 dark:bg-gray-950">
      {voiceError && <p role="alert" className="mb-2 text-sm text-red-600 dark:text-red-300">{voiceError}</p>}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={text}
          onChange={(event) => setText(event.target.value)}
          disabled={disabled}
          placeholder={placeholder}
          className="min-w-0 flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none disabled:opacity-50 dark:border-gray-700 dark:bg-gray-900"
        />
        <VoiceInputButton
          disabled={disabled}
          onTranscript={() => {
            setVoiceError(null);
          }}
          onAutoSubmit={async (transcript) => {
            setVoiceError(null);
            setText("");
            await onSubmit(transcript);
          }}
          onError={setVoiceError}
        />
        <button
          type="submit"
          disabled={disabled || !text.trim()}
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
        >
          보내기
        </button>
      </form>
    </div>
  );
}
