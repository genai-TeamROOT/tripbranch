/*
 * 역할: ChatPage 하단에서 후속 사용자 입력을 받는다.
 * 입력: 텍스트 입력, 요청 중 여부, 제출 콜백, 상황별 placeholder.
 * 출력: 채팅 입력 form.
 * 호출 시점: ChatPage가 대화 하단 입력창을 렌더링할 때 호출된다.
 * TODO: 실제 다회 대화 의미 분석이 생기면 입력 종류와 컨텍스트 전달을 확장한다.
 */

import { Send, Square } from "lucide-react";
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
  /*
   * 둘 다 넘기면 입력값을 부모가 들고 있는다(제어 컴포넌트) — HomePage의 상황
   * 예시 칩처럼 컴포저 밖에서 입력창을 채워야 할 때만 쓴다. 안 넘기면(ChatPage의
   * 기본 사용법) 내부 상태로 그대로 동작한다.
   */
  value?: string;
  onChange?: (value: string) => void;
  /*
   * 전송 버튼의 접근성 이름. HomePage는 "추천 시작하기"처럼 화면의 주된 동작을
   * 그대로 쓴다(버튼 자체는 아이콘만 보이지만, 접근성 이름은 화면마다 의미가
   * 다르다) — 안 넘기면(ChatPage 기본값) 그냥 "보내기"/"Send".
   */
  sendLabel?: string;
  /*
   * 있으면(=응답을 기다리는 중) 전송 버튼 자리가 "중단" 버튼으로 바뀐다
   * (DESIGN_SYSTEM.md §7.2). HomePage의 최초 발화처럼 중단할 대상이 없는
   * 화면은 이 prop을 안 넘기면 기존처럼 비활성 아이콘만 보인다.
   */
  onCancel?: () => void;
}

export function ChatComposer({
  disabled,
  onSubmit,
  placeholder = DEFAULT_PLACEHOLDER,
  language = "ko",
  onPhotoSelect,
  value,
  onChange,
  sendLabel,
  onCancel,
}: ChatComposerProps) {
  const [internalText, setInternalText] = useState("");
  const text = value ?? internalText;
  const setText = onChange ?? setInternalText;
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

  const resolvedSendLabel = sendLabel ?? (language === "en" ? "Send" : "보내기");

  return (
    <div className="sticky bottom-0 z-20 bg-gradient-to-t from-bg via-bg to-bg/0 px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-6 md:mx-auto md:w-full md:max-w-2xl">
      {voiceError && (
        <p role="alert" className="mb-2 text-sm text-rust">
          {voiceError}
        </p>
      )}
      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-1 rounded-full bg-white/70 p-1.5 shadow-card backdrop-blur-md"
      >
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
          className="min-w-0 flex-1 bg-transparent px-1.5 py-2 text-base text-ink placeholder:text-muted focus:outline-none disabled:opacity-50"
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
        {disabled && onCancel ? (
          <button
            type="button"
            onClick={onCancel}
            aria-label={language === "en" ? "Stop" : "중단"}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-rust text-white transition-colors hover:bg-rust/90"
          >
            <Square size={14} className="fill-current" aria-hidden />
          </button>
        ) : (
          <button
            type="submit"
            aria-label={resolvedSendLabel}
            disabled={disabled || !text.trim()}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-brand text-white transition-colors hover:enabled:bg-brand-deep disabled:bg-brand/30"
          >
            <Send size={16} aria-hidden />
          </button>
        )}
      </form>
    </div>
  );
}
