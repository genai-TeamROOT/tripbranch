place_context 판별:
- explicit: 사용자가 장소명을 이번 발화에서 직접 언급 → place_name을 그 장소명으로 채운다
- from_recommendation: "첫 번째", "두 번째", "그 카페" 등 이전 추천 결과를 가리킴 →
  place_name은 null (실제 장소 매칭은 이 서비스가 아니라 상위 레이어가 처리)
- from_conversation: 이전 대화에서 언급된 장소를 가리키지만 추천 결과는 아님 → place_name은 null
