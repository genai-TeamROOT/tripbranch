/*
 * 역할: 사용자의 자유 형식 여행 요청을 입력받고 해석 API를 호출한다.
 * 입력: textarea의 user_input 문자열과 제출 이벤트.
 * 출력: TripContext의 입력/해석 조건 갱신, /confirm 경로 이동, 오류 배너.
 * 호출 시점: 사용자가 첫 화면에서 여행 요청을 작성하고 제출할 때 호출된다.
 * TODO: 예시 프롬프트, 입력 길이 안내, 요청 취소 처리를 추가한다.
 */

import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { interpretUserInput } from "../api/trip";
import { ApiError } from "../api/client";
import { ErrorBanner } from "../components/ErrorBanner";
import { useTripDispatch } from "../state/TripContext";

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
      dispatch({ type: "SET_CONDITIONS", payload: conditions });
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
