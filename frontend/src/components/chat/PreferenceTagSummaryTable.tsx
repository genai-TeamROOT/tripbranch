import type { Language, PreferenceTagSummaryEntry } from "../../types";

interface PreferenceTagSummaryTableProps {
  /* RecommendationItem을 그대로 넘겨도 된다 — 이 모양을 만족한다. */
  items: PreferenceTagSummaryEntry[];
  language: Language;
}

const TAG_BADGE_COLOR = "bg-sky-light text-brand";

export function PreferenceTagSummaryTable({ items, language }: PreferenceTagSummaryTableProps) {
  const taggedItems = items.filter((item) => (item.preference_tags?.length ?? 0) > 0);
  if (taggedItems.length === 0) return null;

  return (
    <section className="overflow-hidden rounded-2xl border border-border bg-white shadow-resting">
      <div className="px-3.5 py-2.5">
        <h3 className="text-sm font-bold text-ink">
          {language === "en" ? "Visitor preference tags by place" : "장소별 방문자 취향 태그"}
        </h3>
        <p className="mt-0.5 text-xs text-muted">
          {language === "en"
            ? "These tags were mentioned across about 30 Naver Blog posts and Google Maps reviews."
            : "네이버 블로그 후기와 구글 지도 리뷰 약 30건에서 언급된 태그입니다."}
        </p>
      </div>
      <table
        className="w-full table-fixed text-left text-sm"
        aria-label={
          language === "en" ? "Visitor preference tags by place" : "장소별 방문자 취향 태그"
        }
      >
        <thead className="border-y border-border text-xs text-muted">
          <tr>
            <th className="w-1/3 px-3.5 py-2 font-medium">
              {language === "en" ? "Place" : "장소"}
            </th>
            <th className="px-3.5 py-2 font-medium">{language === "en" ? "Tags" : "취향 태그"}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {taggedItems.map((item) => (
            <tr key={item.place_id}>
              <th scope="row" className="px-3.5 py-2.5 align-top text-sm font-medium text-ink">
                {item.name}
              </th>
              <td className="px-3.5 py-2">
                <div className="flex flex-nowrap gap-1.5">
                  {item.preference_tags?.slice(0, 2).map((tag) => (
                    <span
                      key={tag.code}
                      className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${TAG_BADGE_COLOR}`}
                    >
                      {tag.label} <span className="text-muted">({tag.mention_count})</span>
                    </span>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
