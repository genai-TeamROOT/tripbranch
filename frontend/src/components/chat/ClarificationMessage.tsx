/*
 * 역할: 인텐트가 모호할 때 되묻기 문구 + 버튼을 채팅 메시지로 보여준다.
 * 입력: 되묻기 문구, 버튼 목록(ClarificationOption[]), 선택 콜백.
 * 출력: assistant 말풍선 스타일 텍스트 + 버튼 목록.
 * 호출 시점: ChatMessageList가 clarification 메시지를 렌더링할 때 호출된다.
 * 버튼 클릭은 텍스트 재전송이 아니라 결정적 override다
 * (docs/design/clarification-options.md 3절) — label은 화면 표시용, id는
 * clarification_choice로 그대로 전송된다.
 */

import type { ClarificationOption } from "../../types";

interface ClarificationMessageProps {
  text: string;
  options: ClarificationOption[];
  isLoading: boolean;
  onSelectOption: (optionId: string, label: string) => void;
}

export function ClarificationMessage({
  text,
  options,
  isLoading,
  onSelectOption,
}: ClarificationMessageProps) {
  return (
    <div className="mr-auto flex max-w-xl flex-col gap-3 rounded-md bg-gray-100 px-4 py-3 text-sm text-gray-800 dark:bg-gray-800 dark:text-gray-100">
      <p className="whitespace-pre-line leading-6">{text}</p>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => (
          <button
            key={option.id}
            type="button"
            disabled={isLoading}
            onClick={() => onSelectOption(option.id, option.label)}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium disabled:opacity-50 dark:border-gray-700"
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
