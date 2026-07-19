// API 에러 메시지를 보여주는 공통 배너 컴포넌트. onRetry가 주어지면 재시도 버튼을 표시.
// 사용법: 각 페이지의 에러 상태(useState<string|null>)를 그대로 message로 넘기면 됨.

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorBanner({ message, onRetry }: ErrorBannerProps) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800 sm:flex-row sm:items-center sm:justify-between"
    >
      <span>{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-md border border-red-300 px-3 py-1 font-medium hover:bg-red-100"
        >
          다시 시도
        </button>
      )}
    </div>
  );
}
