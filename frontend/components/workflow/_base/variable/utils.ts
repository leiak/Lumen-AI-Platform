// frontend/components/workflow/_base/variable/utils.ts
import { BlockEnum, NodeOutPutVar, OutputVar, VarType } from "./types";
import type { WorkflowNode } from "@/services/workflow";

/**
 * Single source of truth: given a node, return the list of typed output variables
 * it exposes to downstream nodes. Mirrors BaseNode.outputs() in the backend.
 */
export function formatItem(node: WorkflowNode): NodeOutPutVar[] {
  const cfg = (node.config ?? {}) as Record<string, any>;
  const title = cfg.title ?? node.id;
  const wrap = (name: string, type: VarType, description?: string): NodeOutPutVar => ({
    variable: name,
    type,
    nodeId: node.id,
    nodeTitle: title,
    description,
  });

  switch (node.type) {
    case BlockEnum.Input: {
      const vars: OutputVar[] = cfg.variables ?? [
        { name: "value", type: VarType.object },
      ];
      return vars.map((v) => wrap(v.name, v.type));
    }
    case BlockEnum.Agent:
      return [
        wrap("response", VarType.string, "Agent 回复"),
        wrap("usage", VarType.object, "调用用量"),
      ];
    case BlockEnum.LLM:
      return [
        wrap("response", VarType.string, "LLM 输出"),
        wrap("model", VarType.string, "使用模型"),
        wrap("finish_reason", VarType.string, "结束原因"),
        wrap("usage", VarType.object, "token 用量"),
      ];
    case BlockEnum.Condition:
      return [
        wrap("result", VarType.boolean),
        wrap("selected_case_id", VarType.string),
      ];
    case BlockEnum.Output:
      return [wrap("value", VarType.object)];
    case BlockEnum.Parallel:
      return [
        wrap("results", VarType.object, "分支结果"),
        wrap("status", VarType.string, "执行状态"),
      ];
    case BlockEnum.FanOut:
      return [wrap("results", VarType.arrayObject, "Fan-Out 结果数组")];
    case BlockEnum.FanIn:
      return [
        wrap("result", VarType.object, "聚合结果"),
        wrap("count", VarType.number, "元素数量"),
      ];
    case BlockEnum.Code:
      return [
        wrap("result", VarType.string, "代码执行结果"),
        wrap("error", VarType.string, "执行错误"),
      ];
    case BlockEnum.HTTP:
      return [
        wrap("status_code", VarType.number, "HTTP 状态码"),
        wrap("body", VarType.object, "响应体"),
        wrap("headers", VarType.object, "响应头"),
        wrap("error", VarType.string, "请求错误"),
      ];
    case BlockEnum.Tool:
      return [
        wrap("result", VarType.string, "工具执行结果"),
        wrap("error", VarType.string, "执行错误"),
      ];
    case BlockEnum.KnowledgeRetrieval:
      return [
        wrap("chunks", VarType.arrayObject, "检索到的文档片段"),
        wrap("count", VarType.number, "片段数量"),
        wrap("error", VarType.string, "检索错误"),
      ];
    case BlockEnum.TemplateTransform:
      return [
        wrap("output", VarType.string, "模板渲染结果"),
        wrap("error", VarType.string, "渲染错误"),
      ];
    case BlockEnum.ParameterExtractor:
      return [
        wrap("parameters", VarType.object, "提取的参数"),
        wrap("error", VarType.string, "提取错误"),
      ];
    case BlockEnum.QuestionClassifier:
      return [
        wrap("category", VarType.string, "分类结果"),
        wrap("confidence", VarType.number, "置信度"),
        wrap("error", VarType.string, "分类错误"),
      ];
    case BlockEnum.VariableAssigner:
      return [
        wrap("result", VarType.object, "赋值结果"),
        wrap("error", VarType.string, "赋值错误"),
      ];
    case BlockEnum.VariableAggregator:
      return [
        wrap("result", VarType.object, "聚合结果"),
        wrap("count", VarType.number, "元素数量"),
        wrap("error", VarType.string, "聚合错误"),
      ];
    case BlockEnum.Start:
    case BlockEnum.End:
    default:
      return [];
  }
}
