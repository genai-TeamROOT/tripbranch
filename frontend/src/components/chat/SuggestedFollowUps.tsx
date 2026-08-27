/*
 * 역할: 한 턴이 끝난 뒤 사용자가 이어서 물을 만한 질문을 버튼으로 보여준다.
 * 입력: 제안 문구 목록, 로딩 여부, 선택 콜백.
 * 출력: assistant 쪽에 붙는 버튼 묶음.
 * 호출 시점: ChatMessageList가 follow_up_suggestions 메시지를 렌더링할 때 호출된다.
 *
 * ClarificationMessage와 생김새는 비슷하지만 동작이 다르다 — 저쪽은 버튼 id를
 * clarification_choice로 보내 Intent를 못 박고, 이쪽은 **문구를 그대로 사용자
 * 발화로 보낸다.** 그래서 여기에는 id가 없고 문자열만 있다.
 */

interface SuggestedFollowUpsProps {
  suggestions: string[];
  isLoading: boolean;
  onSelect: (suggestion: string) => void;
  language: "ko" | "en";
}

export function SuggestedFollowUps({
  suggestions,
  isLoading,
  onSelect,
  language,
}: SuggestedFollowUpsProps) {
  if (suggestions.length === 0) return null;

  const label = language === "en" ? "Suggested next questions" : "이어서 물어볼 만한 질문";

  return (
    <div className="mr-auto flex max-w-xl flex-col gap-2">
      <p className="text-xs text-gray-400 dark:text-gray-500">{label}</p>
      <div className="flex flex-wrap gap-2" role="group" aria-label={label}>
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            disabled={isLoading}
            onClick={() => onSelect(suggestion)}
            className="rounded-full border border-gray-300 px-3 py-1.5 text-sm text-gray-700 disabled:opacity-50 dark:border-gray-700 dark:text-gray-200"
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}
