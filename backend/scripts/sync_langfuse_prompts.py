"""레포의 프롬프트 Markdown과 Langfuse Prompt Management를 맞춘다.

배경: 프롬프트를 Langfuse에서 읽게 되면(`LANGFUSE_PROMPTS_ENABLED=true`) **정본이
      둘이 된다** — git과 Langfuse. 그리고 디스크가 폴백이라, 어긋나면 예외가 아니라
      **조용히 다른 프롬프트로 도는** 상태가 된다. 그게 이 이관의 실제 비용이고
      이 스크립트가 그걸 막는 장치다.

방법: 세 방향. 어느 쪽도 확인 없이는 쓰지 않는다.

  --check  (기본) 읽기만. 43개를 하나씩 대조해 같은지, 없는지, 다른지 낸다.
           다르면 종료코드 1 — 커밋 전·CI에서 돌린다.
  --push   디스크 → Langfuse. **내용이 같으면 올리지 않는다** — create_prompt는
           부를 때마다 새 버전을 만들어서, 무조건 올리면 바뀐 것 없이 버전만
           쌓이고 "언제 뭐가 바뀌었나"를 못 읽게 된다.
  --pull   Langfuse → 디스크. UI에서 고친 것을 레포로 되돌린다. 이걸 안 하면
           레포에 없는 프롬프트로 돈 기록이 남는다.

판정 기준 — 합격/불합격:
  * `--check`가 **하나라도 다르면 불합격**이다. "레포에 없는 지침으로 답변이 나갔다"는
    회귀 판정 자체를 무의미하게 만든다.
  * 원격에만 있고 레포에 없는 이름도 불합격이다 — 지우거나 `--pull` 해야 한다.

실행: cd backend && .venv/bin/python -m scripts.sync_langfuse_prompts
      cd backend && .venv/bin/python -m scripts.sync_langfuse_prompts --push --yes
      cd backend && .venv/bin/python -m scripts.sync_langfuse_prompts --pull --yes

주의: `--push`는 `production` 라벨을 새 버전으로 옮긴다. 즉 **켜져 있는 서버가
      TTL(기본 60초) 안에 새 프롬프트로 갈아탄다.** 배포 없이 바뀌는 게 이 이관의
      목적이지만, 그래서 되돌릴 것을 먼저 확인하고 눌러야 한다.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from dataclasses import dataclass, field
from typing import Any, Final

from app.config import settings
from app.observability.langfuse_prompts import prompt_name
from app.prompts.loader import PROMPT_ROOT, asset_paths
from app.prompts.registry import (
    CONFIG_SEMVER_KEY,
    CONFIG_SLOT_KEY,
    SLOT_ENTRY_TEMPLATES,
    slot_versions,
)

# 서버가 읽는 라벨. Langfuse는 이 라벨이 가리키는 버전을 기본으로 준다.
PRODUCTION_LABEL: Final = "production"

STATUS_SAME: Final = "same"
STATUS_MISSING: Final = "missing"  # 원격에 없다
STATUS_DIFFERENT: Final = "different"
STATUS_ERROR: Final = "error"


@dataclass
class Comparison:
    relative_path: str
    name: str
    disk: str
    remote: str | None
    status: str
    detail: str = ""
    config: dict[str, str] = field(default_factory=dict)
    remote_config: dict[str, Any] = field(default_factory=dict)


def asset_config(relative_path: str) -> dict[str, str]:
    """프롬프트와 함께 올릴 메타데이터.

    **진입 템플릿에만 `semver`가 붙는다.** semver는 슬롯 단위인데 Langfuse 버전은
    파일 단위라, 조각(`_shared/rules/budget`)은 슬롯 여러 개에 걸쳐 있어 값이 하나로
    정해지지 않는다. 진입 템플릿은 슬롯과 1:1이라 모호함이 없다.

    이 값을 `registry.live_slot_version()`이 되읽어 관측의 버전 문자열을 만든다 —
    그래야 기록이 "레포에 적힌 값"이 아니라 "실제로 돈 값"을 말한다.
    """

    for slot, template in SLOT_ENTRY_TEMPLATES.items():
        if template != relative_path:
            continue
        version = slot_versions().get(slot)
        if version is None:
            return {}
        return {CONFIG_SLOT_KEY: slot, CONFIG_SEMVER_KEY: version}
    return {}


def _client() -> Any | None:
    """Langfuse 클라이언트. **`LANGFUSE_PROMPTS_ENABLED`와 무관하게 만든다.**

    스위치는 "서버가 원격을 읽느냐"이고, 이 스크립트는 그걸 켜기 전에 내용을 맞추는
    도구다. 스위치를 요구하면 "켜야 맞출 수 있고, 맞춰야 켤 수 있는" 교착이 된다.
    """

    missing = [
        variable
        for variable, value in (
            ("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key),
            ("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key),
        )
        if not value
    ]
    if missing:
        print(f"✗ 키가 비어 있다: {', '.join(missing)}")
        return None

    from langfuse import Langfuse

    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
        # 이 스크립트는 프롬프트만 다룬다 — span을 만들 일이 없다.
        tracing_enabled=False,
    )
    if not client.auth_check():
        print(f"✗ 인증 실패 — host={settings.langfuse_base_url}")
        return None
    print(f"✓ 인증 확인 — host={settings.langfuse_base_url}")
    return client


def _disk_text(relative_path: str) -> str:
    # loader.load_text()를 쓰지 않는다 — 그건 스위치가 켜져 있으면 원격을 읽어서,
    # 원격과 원격을 비교하게 된다.
    return (PROMPT_ROOT / relative_path).read_text(encoding="utf-8").strip()


def _remote_text(client: Any, name: str) -> tuple[str | None, dict[str, Any], str]:
    """원격 원문. 없으면 `(None, 사유)`.

    `cache_ttl_seconds=0`으로 캐시를 우회한다 — 대조하는 도구가 캐시된 옛 값을 보면
    "같다"는 판정 자체를 믿을 수 없다.
    """

    try:
        prompt = client.get_prompt(name, label=PRODUCTION_LABEL, cache_ttl_seconds=0)
    except Exception as exc:
        message = str(exc)
        if "not found" in message.lower() or "404" in message:
            return None, {}, "원격에 없음"
        return None, {}, f"{type(exc).__name__}: {message[:120]}"
    text = getattr(prompt, "prompt", None)
    config = getattr(prompt, "config", None)
    if not isinstance(text, str):
        return None, {}, f"text 프롬프트가 아니다({type(text).__name__})"
    return text, config if isinstance(config, dict) else {}, ""


def compare_all(client: Any) -> list[Comparison]:
    rows: list[Comparison] = []
    for relative_path in asset_paths():
        name = prompt_name(relative_path)
        disk = _disk_text(relative_path)
        config = asset_config(relative_path)
        remote, remote_config, detail = _remote_text(client, name)
        if remote is None:
            status = STATUS_MISSING if detail == "원격에 없음" else STATUS_ERROR
        elif remote != disk:
            status = STATUS_DIFFERENT
        elif config and {key: remote_config.get(key) for key in config} != config:
            # 본문은 같은데 semver만 다른 경우다 — 버전만 올리고 안 올린 상태.
            # 관측이 옛 버전 문자열을 계속 적으므로 이것도 어긋남이다.
            status = STATUS_DIFFERENT
            detail = (
                f"본문은 같고 config가 다르다 (레포 {config} / 원격 "
                f"{ {key: remote_config.get(key) for key in config} })"
            )
        else:
            status = STATUS_SAME
        rows.append(
            Comparison(relative_path, name, disk, remote, status, detail, config, remote_config)
        )
    return rows


def _print_summary(rows: list[Comparison]) -> None:
    counts = {status: 0 for status in (STATUS_SAME, STATUS_MISSING, STATUS_DIFFERENT, STATUS_ERROR)}
    for row in rows:
        counts[row.status] += 1
    print(
        f"\n같음 {counts[STATUS_SAME]} · 원격에 없음 {counts[STATUS_MISSING]} · "
        f"다름 {counts[STATUS_DIFFERENT]} · 오류 {counts[STATUS_ERROR]}  (총 {len(rows)})"
    )


def run_check(*, show_diff: bool) -> int:
    client = _client()
    if client is None:
        return 1

    rows = compare_all(client)
    for row in rows:
        if row.status == STATUS_SAME:
            continue
        mark = {STATUS_MISSING: "·", STATUS_DIFFERENT: "✗", STATUS_ERROR: "✗"}[row.status]
        print(f"  {mark} {row.relative_path:<40} {row.status} {row.detail}")
        if show_diff and row.status == STATUS_DIFFERENT and row.remote is not None:
            for line in difflib.unified_diff(
                row.remote.splitlines(),
                row.disk.splitlines(),
                fromfile=f"langfuse:{row.name}",
                tofile=f"disk:{row.relative_path}",
                lineterm="",
                n=1,
            ):
                print(f"      {line}")

    # 레포에 없는데 원격에만 있는 이름도 어긋남이다.
    known = {prompt_name(path) for path in asset_paths()}
    try:
        listed = client.api.prompts.list(limit=100)
        orphans = sorted({meta.name for meta in listed.data} - known)
    except Exception as exc:
        orphans = []
        print(f"  · 원격 목록 조회 실패 — {type(exc).__name__}: {exc}")
    for name in orphans:
        print(f"  ✗ {name:<40} 레포에 없음 (지우거나 --pull)")

    _print_summary(rows)
    bad = [row for row in rows if row.status in (STATUS_DIFFERENT, STATUS_ERROR)]
    if bad or orphans:
        print("\n✗ 어긋났다. 디스크가 폴백이라 이 상태는 조용히 다른 프롬프트로 돈다.")
        return 1
    if any(row.status == STATUS_MISSING for row in rows):
        print("\n· 아직 안 올라간 것이 있다 — --push --yes")
        return 0
    print("\n✓ 전부 같다.")
    return 0


def run_push(*, confirmed: bool, message: str) -> int:
    client = _client()
    if client is None:
        return 1

    rows = compare_all(client)
    todo = [row for row in rows if row.status in (STATUS_MISSING, STATUS_DIFFERENT)]
    blocked = [row for row in rows if row.status == STATUS_ERROR]
    if blocked:
        print("\n✗ 조회에 실패한 것이 있어 올리지 않는다 — 덮어쓸지 판단할 근거가 없다:")
        for row in blocked:
            print(f"    {row.relative_path} — {row.detail}")
        return 1

    if not todo:
        print("\n✓ 올릴 것이 없다. 전부 같다.")
        return 0

    print(f"\n=== 올릴 프롬프트 {len(todo)}개 ===")
    for row in todo:
        print(f"  {row.status:<10} {row.relative_path}")
    print(
        f"\n※ '{PRODUCTION_LABEL}' 라벨이 새 버전으로 옮겨간다. "
        f"켜져 있는 서버는 TTL({settings.langfuse_prompt_cache_ttl_seconds}초) 안에 갈아탄다."
    )
    if not confirmed:
        print("\n실제로 올리려면 --yes 를 붙인다.")
        return 0

    failed = 0
    for row in todo:
        try:
            client.create_prompt(
                name=row.name,
                prompt=row.disk,
                labels=[PRODUCTION_LABEL],
                type="text",
                config=row.config or None,
                commit_message=message,
            )
            print(f"  ✓ {row.relative_path}")
        except Exception as exc:
            failed += 1
            print(f"  ✗ {row.relative_path} — {type(exc).__name__}: {exc}")
    return 1 if failed else 0


def run_pull(*, confirmed: bool) -> int:
    client = _client()
    if client is None:
        return 1

    rows = compare_all(client)
    todo = [row for row in rows if row.status == STATUS_DIFFERENT and row.remote is not None]
    if not todo:
        print("\n✓ 되돌릴 것이 없다. 원격에만 있는 변경이 없다.")
        return 0

    print(f"\n=== 디스크를 덮어쓸 파일 {len(todo)}개 ===")
    for row in todo:
        added = len(row.remote.splitlines()) - len(row.disk.splitlines())  # type: ignore[union-attr]
        print(f"  {row.relative_path:<40} 줄 수 {added:+d}")
    if not confirmed:
        print("\n실제로 덮어쓰려면 --yes 를 붙인다. git으로 되돌릴 수 있는지 먼저 확인한다.")
        return 0

    for row in todo:
        # 파일 끝 개행은 레포 관례를 따른다 — strip()해서 비교했으므로 여기서 되붙인다.
        (PROMPT_ROOT / row.relative_path).write_text(
            row.remote.rstrip("\n") + "\n",  # type: ignore[union-attr]
            encoding="utf-8",
        )
        print(f"  ✓ {row.relative_path}")
    print("\n※ 프롬프트 본문이 바뀌었다. 슬롯 버전·HISTORY.md·스냅샷 갱신이 필요하다.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="대조만 한다 (기본)")
    mode.add_argument("--push", action="store_true", help="디스크 → Langfuse")
    mode.add_argument("--pull", action="store_true", help="Langfuse → 디스크")
    parser.add_argument("--yes", action="store_true", help="쓰기를 실제로 실행한다")
    parser.add_argument("--diff", action="store_true", help="--check에서 차이를 함께 낸다")
    parser.add_argument(
        "--message",
        default="레포 동기화 (scripts.sync_langfuse_prompts --push)",
        help="Langfuse 버전에 남길 커밋 메시지",
    )
    args = parser.parse_args()

    if args.push:
        return run_push(confirmed=args.yes, message=args.message)
    if args.pull:
        return run_pull(confirmed=args.yes)
    return run_check(show_diff=args.diff)


if __name__ == "__main__":
    sys.exit(main())
