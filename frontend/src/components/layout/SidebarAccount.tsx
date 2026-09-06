/*
 * 역할: 사이드바 맨 아래 계정 자리. 로그인 안 했으면 로그인 입구, 했으면 아바타+
 *   이름 버튼과 그 팝업(로그아웃).
 * 입력: 없다(신원은 AuthContext에서 직접 읽는다).
 * 출력: /login으로의 이동, 로그아웃(신원 해제 + 이 기기 데이터 정리).
 * 호출 시점: 펼친 사이드바·모바일 드로어(`SideDrawerContent` §6)와 **접힌 레일**
 *   (`DesktopSidebar`)이 각각 렌더한다.
 * 근거: package_D/DESIGN_SYSTEM.md §6.17.
 *
 * **파일을 따로 뺀 이유가 접힌 레일이다**(2026-09-06). 레일은 SideDrawerContent를
 * 아예 렌더하지 않아서 계정에 닿을 길이 없었는데, 레일용으로 한 벌 더 만들면
 * 로그아웃이 두 곳에 생긴다 — 한쪽만 고쳐지면 접었을 때와 폈을 때가 갈린다.
 * 사이드바 안에서 "두 번 만들지 않는다"는 것은 6.17이 드로어와 데스크톱 패널에
 * 이미 적용해 둔 규칙이고, 여기도 같은 이유다.
 *
 * 표시가 갈리는 곳:
 * - **로그인 안 한 상태(게스트)**: 로그인 입구 하나다. 진입이 게스트로 자동으로
 *   열리게 바뀌면서(`RequireUser`) 여기가 로그인으로 가는 유일한 입구가 됐다.
 *   신원 표시를 그리지 않는 이유는, 게스트에게 보여줄 것이 "게스트 / 게스트로
 *   이용 중"뿐이라 이름 자리를 차지하고도 아무것도 알려주지 못하기 때문이다 —
 *   그 자리에는 할 수 있는 동작이 오는 게 낫다.
 * - **계정**: 아바타+이름 버튼 하나를 두고 나머지는 눌렀을 때 팝업으로 낸다
 *   (2026-09-04). 예전에는 신원 라벨 한 줄 + "계정 만들기" + "로그아웃"이 모두
 *   바닥에 펼쳐져 있었다 — 라벨이 `identityLabel`이라 **이메일이 상시 노출**됐고
 *   (이름이 있어도 이메일이 먼저 걸린다), **되돌릴 수 없는 로그아웃이 상시 눌리는
 *   자리**에 있었다.
 *
 * 게스트용 "계정 만들기" 줄은 팝업에서 뺐다(2026-09-06). 게스트는 이제 이 팝업
 * 자체를 보지 않고, 가입은 로그인 화면의 "회원가입" 링크로 닿는다 — 그 화면이
 * 게스트 세션을 그대로 승격시킨다(AuthContext.signUpWithEmail).
 *
 * 팝업에 "프로필"·"설정"·"도움말" 줄은 만들지 않는다. 그 화면이 없다 — 라우트는
 * /, /chat, /preferences, /location, /schedule 뿐이다. 없는 화면 이름을 메뉴에
 * 만들면 눌러도 아무 일이 일어나지 않는다.
 */

import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { LogIn, LogOut } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { identityDisplay, isGuestSession, type IdentityDisplay } from "../../auth/identityLabel";
import { clearLocalUserData } from "../../state/localUserData";
import { useTripDispatch, useTripState } from "../../state/TripContext";

interface SidebarAccountProps {
  /** 모바일 드로어에서만 넘긴다 — 누르면 드로어를 닫기 위해서다. */
  onNavigate?: () => void;
  /**
   * 접힌 레일(72px)용. 아바타·아이콘 하나만 그리고, 팝업은 레일 밖 오른쪽으로
   * 편다 — 레일 폭에 맞추면 이메일이 한 글자씩 끊긴다.
   */
  compact?: boolean;
}

/*
 * 아바타 + 이름 + 부제. **계정 버튼과 팝업 헤더에 같은 모양이 두 번 들어간다** —
 * 따로 적어 두면 한쪽만 고쳐져 팝업을 열 때 이름이 달라 보인다.
 *
 * 아바타는 이름 첫 글자다. 프로필 사진을 받는 경로가 아예 없다(가입은 이름·이메일·
 * 비밀번호만 받고, 소셜 로그인도 없다) — 빈 회색 원을 두면 아직 안 불러온 것처럼
 * 보인다.
 *
 * 겉이 <button>인 자리에도 들어가므로 <div>가 아니라 <span>으로 짠다.
 */
export function IdentityRow({ identity }: { identity: IdentityDisplay }) {
  return (
    <>
      <IdentityAvatar identity={identity} />
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-semibold text-ink">{identity.name}</span>
        <span className="truncate text-[11px] text-muted">{identity.subtitle}</span>
      </span>
    </>
  );
}

function IdentityAvatar({ identity }: { identity: IdentityDisplay }) {
  return (
    <span
      aria-hidden
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-bold text-white"
    >
      {identity.initial}
    </span>
  );
}

const MENU_ITEM_CLASS =
  "flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-medium transition-colors";

/* 레일에서는 다른 아이콘들과 같은 40px 원이다(DesktopSidebar의 RAIL_ICON_CLASS). */
const RAIL_BUTTON_CLASS =
  "flex h-10 w-10 items-center justify-center rounded-full transition-colors hover:bg-chip";

export function SidebarAccount({ onNavigate, compact = false }: SidebarAccountProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const dispatch = useTripDispatch();
  const isEn = useTripState().language === "en";
  const { session, status, signOut } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  if (status !== "ready" || !session) return null;

  const isGuest = isGuestSession(session);
  const identity = identityDisplay(session, isEn ? "en" : "ko");
  const signInLabel = isEn ? "Sign in" : "로그인";
  const railName = `${identity.name} ${identity.subtitle}`;

  async function handleSignOut() {
    try {
      await signOut();
      /* 신원만 끊고 이 기기의 데이터를 두면 다음 신원의 화면에 앞사람의 대화·취향·
         즐겨찾기·검색 위치가 그대로 남는다. 함께 비운다(state/localUserData.ts). */
      clearLocalUserData();
      dispatch({ type: "RESET" });
      /* 이동은 따로 시키지 않는다 — 세션이 사라지면 RequireUser가 게스트 신원을
         새로 발급해 같은 자리에서 앱이 계속 열려 있다. */
    } finally {
      setMenuOpen(false);
      onNavigate?.();
    }
  }

  if (isGuest) {
    return (
      <div className="mt-auto">
        {/* 목적지를 state로 실어 보낸다 — 로그인을 마쳤을 때 홈이 아니라 보던
            화면으로 돌아온다. LoginPage가 이 값을 `from`으로 읽는다. */}
        <button
          type="button"
          title={compact ? signInLabel : undefined}
          aria-label={compact ? signInLabel : undefined}
          onClick={() => {
            navigate("/login", { state: { from: location.pathname } });
            onNavigate?.();
          }}
          className={
            compact
              ? `${RAIL_BUTTON_CLASS} text-brand`
              : "flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-sm font-semibold text-ink transition-colors hover:bg-chip"
          }
        >
          <LogIn size={compact ? 18 : 17} aria-hidden />
          {!compact && signInLabel}
        </button>
      </div>
    );
  }

  return (
    <div className="relative mt-auto">
      {menuOpen && (
        <>
          {/* 대화 줄 메뉴와 같은 방식이다 — 바깥을 누르면 닫힌다. */}
          <button
            type="button"
            aria-label={isEn ? "Close account menu" : "계정 메뉴 닫기"}
            onClick={() => setMenuOpen(false)}
            className="fixed inset-0 z-20 cursor-default"
          />
          {/*
           * 계정 버튼이 사이드바 맨 아래라 위로 띄운다(bottom-full). 접힌 레일에서는
           * 폭을 레일에 맞출 수 없어(72px) 고정 폭으로 오른쪽에 편다 — .tb-sidebar에
           * overflow가 없어 밖으로 나갈 수 있다.
           */}
          <div
            className={`absolute bottom-full z-30 mb-2 flex flex-col rounded-2xl bg-white p-1.5 shadow-card ${
              compact ? "left-0 w-60" : "left-0 right-0"
            }`}
          >
            {/* 어느 계정의 메뉴인지 팝업 안에서도 보인다 — 팝업이 계정 버튼을 덮는
                자리에 뜨기 때문이다. 누를 수는 없다(계정 화면이 없다). */}
            <div className="flex items-center gap-2.5 px-2 py-2">
              <IdentityRow identity={identity} />
            </div>
            <div className="mx-2 my-1 h-px bg-border" />
            {/* role="menu" 는 menuitem 만 감싼다 — 위의 신원 헤더는 menuitem 이 아니다. */}
            <div role="menu" aria-label={isEn ? "Account" : "계정"} className="flex flex-col">
              <button
                type="button"
                role="menuitem"
                onClick={() => void handleSignOut()}
                className={`${MENU_ITEM_CLASS} text-rust hover:bg-chip`}
              >
                <LogOut size={15} aria-hidden />
                {isEn ? "Sign out" : "로그아웃"}
              </button>
            </div>
          </div>
        </>
      )}
      {/*
       * 이름을 읽어주는 것이 이 버튼의 이름이다 — aria-label로 "계정 메뉴"라고 덮으면
       * 어느 계정인지 소리로 확인할 방법이 없어진다. 무엇이 열리는지는 aria-haspopup이
       * 알린다.
       *
       * 레일에는 글자가 없어 이름이 저절로 붙지 않으므로 그때만 직접 준다. **펼친
       * 쪽과 같은 문구**여야 한다 — 펼친 버튼은 이름과 부제를 둘 다 품고 있어 그
       * 둘이 이어져 읽힌다. 같은 버튼이 접힘/펼침에 따라 다른 이름을 가지면 안 된다
       * (DesktopSidebar의 레일 라벨과 같은 근거).
       */}
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        title={compact ? railName : undefined}
        aria-label={compact ? railName : undefined}
        onClick={() => setMenuOpen((open) => !open)}
        className={
          compact
            ? RAIL_BUTTON_CLASS
            : "flex w-full items-center gap-2.5 rounded-xl px-2 py-2 text-left transition-colors hover:bg-chip"
        }
      >
        {compact ? <IdentityAvatar identity={identity} /> : <IdentityRow identity={identity} />}
      </button>
    </div>
  );
}
