/*
 * 역할: 30분이 지난 브라우저 위치를 계속 쓸지, 새 위치를 받을지 채팅 안에서 묻는다.
 * 입력: 마지막 위치 확인 경과 시간과 두 선택지 콜백.
 * 출력: 기존 위치 유지/현재 위치 갱신 버튼이 있는 assistant 말풍선.
 */

interface LocationRefreshMessageProps {
  ageMinutes: number | null;
  isLoading: boolean;
  onUsePrevious: () => void;
  onRefreshLocation: () => void;
}

export function LocationRefreshMessage({
  ageMinutes,
  isLoading,
  onUsePrevious,
  onRefreshLocation,
}: LocationRefreshMessageProps) {
  const previousLocationLabel = ageMinutes === null ? "이전 위치로 계속" : `${ageMinutes}분 전 위치로 계속`;

  return (
    <div className="mr-auto flex max-w-xl flex-col gap-3 rounded-md bg-gray-100 px-4 py-3 text-sm text-gray-800 dark:bg-gray-800 dark:text-gray-100">
      <p className="leading-6">
        {ageMinutes === null
          ? "현재 위치를 확인한 시각을 알 수 없어요. 이번 추천에 사용할 위치를 선택해주세요."
          : `현재 위치를 확인한 지 ${ageMinutes}분이 지났어요. 이번 추천에 사용할 위치를 선택해주세요.`}
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={isLoading}
          onClick={onUsePrevious}
          className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium disabled:opacity-50 dark:border-gray-700"
        >
          {previousLocationLabel}
        </button>
        <button
          type="button"
          disabled={isLoading}
          onClick={onRefreshLocation}
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
        >
          현재 위치 다시 가져오기
        </button>
      </div>
    </div>
  );
}
