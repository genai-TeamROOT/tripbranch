import type { Language, RecommendationItem } from "../../types";

interface PreferenceTagSummaryTableProps {
  items: RecommendationItem[];
  language: Language;
}

const TAG_COLORS: Record<string, string> = {
  date: "bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-200",
  with_parents: "bg-orange-50 text-orange-700 dark:bg-orange-950/30 dark:text-orange-200",
  with_friends: "bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-200",
  with_kids: "bg-yellow-50 text-yellow-700 dark:bg-yellow-950/30 dark:text-yellow-200",
  alone: "bg-slate-50 text-slate-700 dark:bg-slate-900/40 dark:text-slate-200",
  photo_spot: "bg-pink-50 text-pink-700 dark:bg-pink-950/30 dark:text-pink-200",
  good_view: "bg-sky-50 text-sky-700 dark:bg-sky-950/30 dark:text-sky-200",
  night_visit: "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-200",
  healing: "bg-teal-50 text-teal-700 dark:bg-teal-950/30 dark:text-teal-200",
  quiet: "bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-200",
  cozy: "bg-violet-50 text-violet-700 dark:bg-violet-950/30 dark:text-violet-200",
  experience: "bg-purple-50 text-purple-700 dark:bg-purple-950/30 dark:text-purple-200",
  unique: "bg-fuchsia-50 text-fuchsia-700 dark:bg-fuchsia-950/30 dark:text-fuchsia-200",
  culture_art: "bg-lime-50 text-lime-700 dark:bg-lime-950/30 dark:text-lime-200",
  indoor: "bg-cyan-50 text-cyan-700 dark:bg-cyan-950/30 dark:text-cyan-200",
  walk: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-200",
  nature: "bg-green-50 text-green-700 dark:bg-green-950/30 dark:text-green-200",
  food_exploration: "bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-200",
};

const FALLBACK_COLOR = "bg-gray-50 text-gray-600 dark:bg-gray-900/40 dark:text-gray-200";

export function PreferenceTagSummaryTable({ items, language }: PreferenceTagSummaryTableProps) {
  const taggedItems = items.filter((item) => (item.preference_tags?.length ?? 0) > 0);
  if (taggedItems.length === 0) return null;

  return (
    <section className="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
      <div className="bg-gray-50 px-3 py-2 dark:bg-gray-800/70">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200">
          {language === "en" ? "Visitor preference tags by place" : "장소별 방문자 취향 태그"}
        </h3>
        <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
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
        <thead className="border-y border-gray-200 bg-white text-xs text-gray-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400">
          <tr>
            <th className="w-1/3 px-3 py-2 font-medium">{language === "en" ? "Place" : "장소"}</th>
            <th className="px-3 py-2 font-medium">{language === "en" ? "Tags" : "취향 태그"}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-800 dark:bg-gray-900">
          {taggedItems.map((item) => (
            <tr key={item.place_id}>
              <th
                scope="row"
                className="px-3 py-2.5 align-top text-sm font-medium text-gray-800 dark:text-gray-200"
              >
                {item.name}
              </th>
              <td className="px-3 py-2">
                <div className="flex flex-wrap gap-1.5">
                  {item.preference_tags?.slice(0, 3).map((tag) => (
                    <span
                      key={tag.code}
                      className={`rounded-full px-2.5 py-1 text-xs font-medium ${TAG_COLORS[tag.code] ?? FALLBACK_COLOR}`}
                    >
                      {tag.label} ({tag.mention_count})
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
