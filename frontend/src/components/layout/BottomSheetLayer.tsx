/*
 * 역할: 시트로 열린 화면 하나를 아래에서 올라오는 바텀시트로 감싼다.
 * 입력: 시트 안에 그릴 children, 스택에서의 깊이(depth, 겹쳤을 때 z-index용),
 *   바깥 클릭·닫기 버튼 클릭 시 호출할 onDismiss.
 * 호출 시점: AppShell이 sheetLocations 각각을 이 컴포넌트로 감싼다.
 * 근거: package_D/DESIGN_SYSTEM.md §5.2.
 *
 * ⚠️ children 루트는 h-full이어야 한다(min-h-dvh 아님) — 아니면 overflow-hidden에
 * 잘려 하단 내용이 안 보이고 스크롤도 안 된다(§5 "높이 체인 주의").
 */

import { AnimatePresence, motion } from "framer-motion";
import type { ReactNode } from "react";

interface BottomSheetLayerProps {
  children: ReactNode;
  depth: number;
  onDismiss: () => void;
}

export function BottomSheetLayer({ children, depth, onDismiss }: BottomSheetLayerProps) {
  return (
    <AnimatePresence>
      <div className="absolute inset-0 z-30" style={{ zIndex: 30 + depth }}>
        <motion.button
          type="button"
          aria-label="닫기"
          onClick={onDismiss}
          className="absolute inset-0 bg-ink-strong/35"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.22 }}
        />
        <motion.div
          className="absolute inset-x-0 bottom-0 top-3 flex flex-col overflow-hidden rounded-t-3xl bg-bg shadow-card"
          initial={{ y: "100%" }}
          animate={{ y: 0 }}
          exit={{ y: "100%" }}
          transition={{ type: "spring", damping: 32, stiffness: 320 }}
        >
          {children}
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
