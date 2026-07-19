// 첫 화면("/"): 자유 텍스트 입력을 받아 /api/interpret 호출 후 /confirm으로 이동.
// 로딩/에러 상태를 로컬 useState로 관리하고, 성공 시에만 전역 상태(user_input,
// interpreted_conditions)를 dispatch한다. 사용법 및 방향: 입력 검증(길이 제한 등)을
// 강화하려면 이 파일의 handleSubmit에서 처리할 것.

import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { interpretUserInput } from "../api/interpret";
import { ApiError } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";
import { useTripDispatch } from "../context/useTripDispatch";

export function InputPage() {
  const dispatch = useTripDispatch();
  const navigate = useNavigate();

  const [userInput, setUserInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!userInput.trim() || isLoading) return;

    setIsLoading(true);
    setErrorMessage(null);

    try {
      const conditions = await interpretUserInput(userInput);
      dispatch({ type: "SET_USER_INPUT", payload: userInput });
      dispatch({ type: "SET_INTERPRETED_CONDITIONS", payload: conditions });
      navigate("/confirm");
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError ? error.message : "입력을 처리하지 못했어요. 다시 시도해주세요.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-4 px-4 py-10">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">TripBranch</h1>
      <p className="text-sm text-gray-600 dark:text-gray-400">
        지금 상황과 원하는 조건을 자유롭게 적어주세요. 예: "경복궁 근처에서 비를 피할 수 있는
        박물관이나 카페를 찾고 싶어"
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <textarea
          value={userInput}
          onChange={(event) => setUserInput(event.target.value)}
          rows={5}
          placeholder="예: 경복궁 근처에서 비를 피할 수 있는 박물관이나 카페를 찾고 싶어"
          className="w-full resize-none rounded-md border border-gray-300 p-3 text-sm focus:border-gray-500 focus:outline-none dark:border-gray-700 dark:bg-gray-900"
        />

        {errorMessage && <ErrorBanner message={errorMessage} />}

        <button
          type="submit"
          disabled={isLoading || !userInput.trim()}
          className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900"
        >
          {isLoading ? "분석 중..." : "조건 확인하기"}
        </button>
      </form>
    </main>
  );
}
