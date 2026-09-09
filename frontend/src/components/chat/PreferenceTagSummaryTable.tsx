import { useState } from "react";

import type { Language, PreferenceTagSummaryEntry } from "../../types";

interface PreferenceTagSummaryTableProps {
  /* RecommendationItem을 그대로 넘겨도 된다 — 이 모양을 만족한다. */
  items: PreferenceTagSummaryEntry[];
  language: Language;
}

export function PreferenceTagSummaryTable({ items, language }: PreferenceTagSummaryTableProps) {
  const [isSourceOpen, setIsSourceOpen] = useState(false);
  const taggedItems = items.filter((item) => (item.preference_tags?.length ?? 0) > 0);
  if (taggedItems.length === 0) return null;

  return (
    <section>
      <div className="overflow-hidden rounded-2xl border border-border/70 bg-white shadow-resting">
        <div className="flex items-start justify-between gap-2 px-4 pb-2 pt-3.5">
          <h3 className="text-base font-semibold tracking-tight text-ink">
            {language === "en" ? "Visitor preference tags by place" : "장소별 방문자 취향 태그"}
          </h3>
          <span className="relative inline-flex shrink-0">
            <button
              type="button"
              aria-label={language === "en" ? "Show tag sources" : "태그 출처 보기"}
              aria-expanded={isSourceOpen}
              onMouseEnter={() => setIsSourceOpen(true)}
              onMouseLeave={() => setIsSourceOpen(false)}
              onFocus={() => setIsSourceOpen(true)}
              onBlur={() => setIsSourceOpen(false)}
              onClick={() => setIsSourceOpen((open) => !open)}
              className="flex h-4 w-4 items-center justify-center rounded-full text-[11px] font-bold leading-none text-muted hover:text-label focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
            >
              ⓘ
            </button>
            {isSourceOpen && (
              <p
                role="tooltip"
                className="absolute right-0 top-full z-10 mt-1 w-60 rounded-lg border border-border bg-surface px-2.5 py-2 text-right text-[11px] text-muted shadow-card"
              >
                {language === "en"
                  ? "Source: Naver Blog posts and Google Maps reviews (about 30 per place)"
                  : "출처: 네이버 블로그 후기 · 구글 지도 리뷰(장소별 약 30건)"}
              </p>
            )}
          </span>
        </div>
        <table
          className="w-full table-fixed text-left text-sm"
          aria-label={
            language === "en" ? "Visitor preference tags by place" : "장소별 방문자 취향 태그"
          }
        >
          <thead className="sr-only">
            <tr>
              <th className="w-1/3">{language === "en" ? "Place" : "장소"}</th>
              <th>{language === "en" ? "Tags" : "취향 태그"}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {taggedItems.map((item) => (
              <tr key={item.place_id}>
                <th scope="row" className="w-1/3 px-4 py-3 align-top text-[13px] font-medium text-ink">
                  {item.name}
                </th>
                <td className="px-4 py-2.5">
                  <div className="flex flex-nowrap gap-1.5">
                    {item.preference_tags?.slice(0, 2).map((tag) => (
                      <span
                        key={tag.code}
                        className="flex items-center gap-1 whitespace-nowrap rounded-full bg-sky-light px-2.5 py-1 text-[11px] font-semibold text-label"
                      >
                        {tag.label}
                        <span className="font-normal text-muted">({tag.mention_count})</span>
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
