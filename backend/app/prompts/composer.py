"""정적 Markdown 조각과 동적 대화 컨텍스트를 조립하는 공통 도우미."""

from __future__ import annotations


def join_sections(*sections: str) -> str:
    """비어 있지 않은 섹션만 빈 줄 하나로 구분해 합친다."""

    return "\n\n".join(section.strip() for section in sections if section.strip())
