/*
 * 역할: ChatPage 하단에서 후속 사용자 입력을 받는다.
 * 입력: 텍스트 입력, 요청 중 여부, 제출 콜백, 상황별 placeholder.
 * 출력: 채팅 입력 form.
 * 호출 시점: ChatPage가 대화 하단 입력창을 렌더링할 때 호출된다.
 * TODO: 실제 다회 대화 의미 분석이 생기면 입력 종류와 컨텍스트 전달을 확장한다.
 */

import { useState, type FormEvent } from "react";
import type { Language } from "../../types";
import { PhotoInputButton } from "./PhotoInputButton";
import { VoiceInputButton } from "./VoiceInputButton";

const DEFAULT_PLACEHOLDER = "추가 조건을 입력해 주세요";

interface ChatComposerProps {
  disabled: boolean;
  onSubmit: (text: string) => Promise<void>;
  /* 되묻기처럼 특정 형태의 답변이 필요할 때 예시 문장을 안내한다. */
  placeholder?: string;
  language?: Language;
  /*
   * "+" 버튼으로 고른 사진. 안 넘기면 버튼 자체를 그리지 않는다 — 붙일 곳이
   * 준비되지 않은 화면에서 눌러도 아무 일이 없는 버튼을 보이지 않게 한다.
   */
  onPhotoSelect?: (file: File) => Promise<void> | void;
}

export function ChatComposer({
  disabled,
  onSubmit,
  placeholder = DEFAULT_PLACEHOLDER,
  language = "ko",
  onPhotoSelect,
}: ChatComposerProps) {
  const [text, setText] = useState("");
  // 음성과 사진이 같은 자리에 오류를 띄운다. 하나만 두면 뒤에 난 오류가 앞의 것을
  // 덮어쓰는데, 둘을 동시에 쓰는 흐름이 아니라 그 편이 자연스럽다.
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
        {onPhotoSelect && (
          <PhotoInputButton
            disabled={disabled}
            onSelect={async (file) => {
              setVoiceError(null);
              await onPhotoSelect(file);
            }}
            onError={setVoiceError}
          />
        )}
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
          onManualStop={(transcript) => {
            setVoiceError(null);
            setText(transcript);
          }}
          onError={setVoiceError}
        />
        <button
          type="submit"
          disabled={disabled || !text.trim()}
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
        >
          {language === "en" ? "Send" : "보내기"}
        </button>
      </form>
    </div>
  );
}
