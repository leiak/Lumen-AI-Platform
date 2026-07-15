// frontend/components/workflow/_base/variable/VarReferencePopup.tsx
import { Popover } from "antd";
import type { ReactNode } from "react";
import type { Var } from "./types";
import { VarReferenceVars } from "./VarReferenceVars";

export function VarReferencePopup({
  open,
  onOpenChange,
  vars,
  onPick,
  children,
}: {
  open: boolean;
  onOpenChange: (b: boolean) => void;
  vars: Var[];
  onPick: (v: Var) => void;
  children: ReactNode;
}) {
  return (
    <Popover
      open={open}
      onOpenChange={onOpenChange}
      trigger="click"
      placement="bottomLeft"
      getPopupContainer={() => document.body}
      content={
        <div style={{ width: 320, maxHeight: 360, overflowY: "auto" }}>
          <VarReferenceVars vars={vars} onPick={onPick} />
        </div>
      }
    >
      {children}
    </Popover>
  );
}
