place_types / place_tags 규칙:
- place_tags가 있으면 소속 place_types를 자동으로 함께 채운다 (예: "카페" → restaurant)
- place_types만 있고 place_tags가 없으면 해당 유형 전체를 의미 (place_tags: [])
- 아무 유형도 언급하지 않았으면 둘 다 빈 배열 (전체 검색)
- 복수 유형이 언급되면 언급 순서대로 모두 담는다 (예: "박물관이나 카페" →
  place_types: [cultural_facility, restaurant], place_tags: [박물관, 카페])
- **행사를 가리키는 말은 담지 않는다.** 축제·행사·전시회·공연·콘서트는 장소가 아니라
  기간이 있는 행사라 장소 추천이 다루지 않는다 — festival 유형과 축제·전시회·공연·
  콘서트 태그를 쓰지 말고, 그 말만 있으면 place_types·place_tags를 모두 빈 배열로 둔다.
  건물을 가리키는 말은 그대로 담는다 (미술관 → cultural_facility/미술관, 공연장 →
  cultural_facility/공연장)
