/*
 * 역할: 아직 실제 콘텐츠가 없는 화면의 임시 자리. 헤더·레이아웃 배선만 먼저 검증한다.
 * 입력: 화면 제목.
 * 출력: 없음.
 * 호출 시점: PreferencesPage/LocationPage/SchedulePage가 실제 콘텐츠를 받기 전까지.
 * TODO: 각 화면이 실제 콘텐츠를 받으면 이 컴포넌트 사용을 지운다.
 */

import { useNavigate } from "react-router-dom";
import { AppHeader } from "../components/layout/AppHeader";

export function PlaceholderPage({ title }: { title: string }) {
  const navigate = useNavigate();

  return (
    <main className="flex h-full flex-col overflow-y-auto">
      <AppHeader onBack={() => navigate(-1)} />
      <div className="flex flex-1 flex-col px-4 pb-10">
        <h1 className="text-[24px] font-bold leading-snug text-ink">{title}</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted">아직 준비 중이에요.</p>
      </div>
    </main>
  );
}
