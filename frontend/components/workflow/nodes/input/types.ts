// frontend/components/workflow/nodes/input/types.ts
import { VarType } from "@/components/workflow/_base/variable/types";

export interface InputVariable {
  name: string;
  type: VarType;
  required: boolean;
  default?: unknown;
}

export const ALL_VAR_TYPES: VarType[] = [
  VarType.string,
  VarType.number,
  VarType.boolean,
  VarType.object,
  VarType.arrayString,
  VarType.arrayNumber,
  VarType.arrayObject,
  VarType.file,
];
