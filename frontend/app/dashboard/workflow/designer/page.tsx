"use client";

import { useState, useCallback, useEffect, useMemo, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  addEdge,
  useNodesState,
  useEdgesState,
  Connection,
  Edge,
  Node,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Card,
  Button,
  Input,
  Space,
  Select,
  Form,
  Tag,
  App,
  Collapse,
  Tooltip,
} from "antd";
import {
  SaveOutlined,
  PlusOutlined,
  PlayCircleOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { workflowApi, Workflow } from "@/services/workflow";
import { getPanelForType } from "@/components/workflow/nodes/registry";
import { RunResultPanel } from "@/components/workflow/designer/RunResultPanel";
import { InputValuesModal, type InputVarSpec } from "@/components/workflow/designer/InputValuesModal";
// M30c: import the P2 node components + the per-node metadata used by
// the left-side NodeLibraryPanel. The 9 P2 Node.tsx files were already
// shipped with P2 (Code/HTTP/Tool/KB/TemplateTransform/PE/QC/VA/VAgg)
// but never wired into the canvas — that gap is closed by merging
// `p2NodeComponents` into the canvas's `nodeTypes` map below.
import {
  p2NodeComponents,
  P2_NODE_REGISTRY_LIST,
  CATEGORY_LABELS,
  NodeCategory,
} from "./nodeTypes";
import { wouldCreateCycle } from "./hooks/wouldCreateCycle";

// ---------------------------------------------------------------------------
// Custom node components
// ---------------------------------------------------------------------------

const InputNode = ({ data }: { data: any }) => (
  <Card size="small" style={{ minWidth: 150, background: "#f0f0f0" }}>
    <Handle type="target" position={Position.Top} />
    <div style={{ fontWeight: "bold" }}>📥 Input</div>
    <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
    <Handle type="source" position={Position.Bottom} />
  </Card>
);

const AgentNode = ({ data }: { data: any }) => (
  <Card size="small" style={{ minWidth: 150, background: "#e6f7ff" }}>
    <Handle type="target" position={Position.Top} />
    <div style={{ fontWeight: "bold" }}>🤖 Agent</div>
    <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
    <Handle type="source" position={Position.Bottom} />
  </Card>
);

const LLMNode = ({ data }: { data: any }) => {
  const modelLabel = data?.model_name || "未配置模型";
  const hasPrompt = Boolean(data?.prompt?.trim());
  return (
    <Card
      size="small"
      style={{
        minWidth: 180,
        background: "linear-gradient(135deg, #f9f0ff 0%, #efdbff 100%)",
        borderColor: "#b37feb",
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div style={{ fontWeight: "bold", color: "#531dab" }}>✨ LLM</div>
      <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
      <div style={{ fontSize: 11, marginTop: 4 }}>
        <Tag color="purple" style={{ marginRight: 4 }}>
          {modelLabel}
        </Tag>
        {hasPrompt ? (
          <Tag color="green">prompt</Tag>
        ) : (
          <Tag color="default">未填写 prompt</Tag>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </Card>
  );
};

const ConditionNode = ({ data }: { data: any }) => (
  <Card size="small" style={{ minWidth: 150, background: "#fff7e6" }}>
    <Handle type="target" position={Position.Top} />
    <div style={{ fontWeight: "bold" }}>🔀 Condition</div>
    <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
    <Handle type="source" position={Position.Bottom} style={{ left: "30%" }} />
    <Handle type="source" position={Position.Bottom} style={{ left: "70%" }} />
  </Card>
);

const OutputNode = ({ data }: { data: any }) => (
  <Card size="small" style={{ minWidth: 150, background: "#f6ffed" }}>
    <Handle type="target" position={Position.Top} />
    <div style={{ fontWeight: "bold" }}>📤 Output</div>
    <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
  </Card>
);

const ParallelNode = ({ data }: { data: any }) => (
  <Card size="small" style={{ minWidth: 150, background: "#fff0f6" }}>
    <Handle type="target" position={Position.Top} />
    <div style={{ fontWeight: "bold" }}>⚡ Parallel</div>
    <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
    <Handle type="source" position={Position.Bottom} style={{ left: "30%" }} />
    <Handle type="source" position={Position.Bottom} style={{ left: "70%" }} />
  </Card>
);

const FanOutNode = ({ data }: { data: any }) => (
  <Card size="small" style={{ minWidth: 150, background: "#f0f5ff" }}>
    <Handle type="target" position={Position.Top} />
    <div style={{ fontWeight: "bold" }}>🔱 Fan-Out</div>
    <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
    <Handle type="source" position={Position.Bottom} />
  </Card>
);

const FanInNode = ({ data }: { data: any }) => (
  <Card size="small" style={{ minWidth: 150, background: "#fffbe6" }}>
    <Handle type="target" position={Position.Top} />
    <Handle type="target" position={Position.Left} />
    <div style={{ fontWeight: "bold" }}>🔻 Fan-In</div>
    <div style={{ fontSize: 12, color: "#666" }}>{data.label}</div>
    <Handle type="source" position={Position.Bottom} />
  </Card>
);

const nodeTypes = {
  // M30c: merge P2 components into the canvas map. P1 stays inline
  // (preserves the pre-M30c visual style); P2 ships as Node.tsx.
  ...p2NodeComponents,
  input: InputNode,
  agent: AgentNode,
  llm: LLMNode,
  condition: ConditionNode,
  output: OutputNode,
  parallel: ParallelNode,
  fan_out: FanOutNode,
  fan_in: FanInNode,
};

const initialNodes: Node[] = [
  { id: (typeof crypto !== "undefined" && crypto.randomUUID && crypto.randomUUID()) || `n-${Date.now()}`, type: "input", position: { x: 250, y: 0 }, data: { label: "User Input" } },
];

const initialEdges: Edge[] = [];

// ---------------------------------------------------------------------------
// Node library — left sidebar
// ---------------------------------------------------------------------------

interface NodeLibEntry {
  type: string;
  label: string;
  icon: string;
  description: string;
  color: string;
}

const P1_NODE_LIB: NodeLibEntry[] = [
  { type: "input", label: "输入节点", icon: "📥", description: "定义工作流输入变量", color: "#f0f0f0" },
  { type: "agent", label: "Agent 节点", icon: "🤖", description: "多轮对话 Agent", color: "#e6f7ff" },
  { type: "llm", label: "LLM 节点", icon: "✨", description: "大语言模型调用", color: "#f9f0ff" },
  { type: "condition", label: "条件节点", icon: "🔀", description: "条件分支路由", color: "#fff7e6" },
  { type: "output", label: "输出节点", icon: "📤", description: "定义工作流输出", color: "#f6ffed" },
  { type: "parallel", label: "并行节点", icon: "⚡", description: "并行执行多条路径", color: "#fff0f6" },
  { type: "fan_out", label: "Fan-Out 节点", icon: "🔱", description: "一对多分发", color: "#f0f5ff" },
  { type: "fan_in", label: "Fan-In 节点", icon: "🔻", description: "多合一汇聚", color: "#fffbe6" },
];

// Merge P1 + P2 into one flat list annotated with category
const ALL_NODE_LIB: (NodeLibEntry & { category: NodeCategory })[] = [
  ...P1_NODE_LIB.map((n) => ({ ...n, category: "input" as NodeCategory })),
  ...P2_NODE_REGISTRY_LIST.map((meta) => ({
    type: meta.type as string,
    label: meta.label,
    icon: meta.icon,
    description: meta.description,
    color: meta.color,
    category: meta.category,
  })),
];

// Group by category in display order
const CATEGORY_ORDER: NodeCategory[] = ["input", "process", "control", "variable", "integration", "output"];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function WorkflowDesignerPageContent() {
  const searchParams = useSearchParams();
  const workflowIdFromUrl = searchParams.get("id");

  // App.useApp() returns a context-bound message instance bound to the
  // <App> wrapper in dashboard/layout.tsx. The static `import { message }`
  // API works in many cases but is unreliable inside Next.js client
  // components (React strict mode double-mount can drop the global toast
  // container) — switching to the context-bound instance makes the save
  // success/failure toast actually appear.
  const { message } = App.useApp();

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesState] = useEdgesState(initialEdges);
  const [workflowName, setWorkflowName] = useState("新工作流");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<number | undefined>(
    workflowIdFromUrl ? parseInt(workflowIdFromUrl) : undefined
  );

  const [runResult, setRunResult] = useState<any | null>(null);
  const [runLoading, setRunLoading] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  // M30c: M30a `WorkflowNodeRun` rows for the just-finished run.
  // Passed to RunResultPanel so the timeline can show per-node
  // duration / status / error / input_data / output_data.
  const [runNodeRuns, setRunNodeRuns] = useState<any[] | null>(null);

  // Set when the user clicks 运行 and the workflow has an input node with
  // variables. While non-null, the InputValuesModal is open and the actual
  // run is paused until the user provides values.
  const [pendingVariables, setPendingVariables] = useState<InputVarSpec[] | null>(null);

  // The workflow convention is exactly one input node at the start. If the
  // user has more than one, take the first; if none, return [].
  function collectInputVariables(ns: typeof nodes): InputVarSpec[] {
    const inputNode = ns.find((n) => n.type === "input");
    if (!inputNode) return [];
    // Variables live in `data` on React Flow Node (the InputPanel writes
    // them there via updateNodeData). The plan text says `config` — that
    // would be the persisted shape; at runtime we read `data`.
    const cfg = ((inputNode.data as Record<string, any>) ?? {}) as {
      variables?: InputVarSpec[];
    };
    return (cfg.variables ?? []).map((v) => ({
      name: v.name,
      type: (v.type ?? "string") as InputVarSpec["type"],
      required: v.required ?? false,
    }));
  }

  // Save status state — displayed inline next to the save button so the
  // user always sees feedback even if the toast is missed or hidden.
  //   "idle"   → no save attempted yet for this workflow
  //   "saving" → request in flight
  //   "saved"  → last save succeeded; show "已保存 X 秒前"
  //   "error"  → last save failed; show error + retry button
  const [saveStatus, setSaveStatus] = useState<
    "idle" | "saving" | "saved" | "error"
  >("idle");
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [saveErrorMsg, setSaveErrorMsg] = useState<string | null>(null);
  // `now` ticks every 5s while the panel is mounted so the "X 秒前"
  // label refreshes on its own without re-rendering the whole tree.
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    const fetchWorkflows = async () => {
      try {
        const res = await workflowApi.list(1, 100);
        // Backend returns PaginatedResponse[T] = {code, message, data: [...], total, page, page_size}.
        // res.data is the wrapper, res.data.data is the actual array.
        setWorkflows(res.data.data || []);
        // If workflowIdFromUrl is set, auto-select it
        if (workflowIdFromUrl) {
          const id = parseInt(workflowIdFromUrl);
          const wf = (res.data.data || []).find((w: Workflow) => w.id === id);
          if (wf) {
            // Pass the just-loaded workflow directly. The list setState above
            // hasn't been reflected in `workflows` yet, so without this the
            // handler would read a stale empty state and bail out, leaving
            // the canvas empty.
            handleWorkflowSelect(id, wf);
          }
        }
      } catch (error) {
        message.error("加载工作流列表失败");
      }
    };
    fetchWorkflows();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowIdFromUrl]);

  // Tick `now` so the "已保存 X 秒前" label stays fresh. No-op when the
  // status is anything other than "saved" — the timer is only useful
  // while we're displaying the relative-time string.
  useEffect(() => {
    if (saveStatus !== "saved") return;
    const t = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(t);
  }, [saveStatus]);

  const formatRelative = useCallback(
    (date: Date) => {
      const sec = Math.max(0, Math.floor((now - date.getTime()) / 1000));
      if (sec < 5) return "刚刚";
      if (sec < 60) return `${sec} 秒前`;
      if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
      return date.toLocaleTimeString();
    },
    [now]
  );

  const onConnect = useCallback(
    (params: Connection) => {
      // M30 收口-C: validate the connection before adding it.
      // Reject self-loops, missing endpoints, and cycle-creating
      // edges. The user sees a warning instead of a silently-broken
      // workflow.
      if (!params.source || !params.target) return;
      if (params.source === params.target) {
        message.warning("不允许自环:不能把节点连到自己");
        return;
      }
      const sourceNode = nodes.find((n) => n.id === params.source);
      const targetNode = nodes.find((n) => n.id === params.target);
      if (!sourceNode || !targetNode) {
        // Edge references a node that no longer exists (race during
        // multi-user edit). Silently ignore — the stale edge will
        // be cleaned up on the next save.
        return;
      }
      // Source nodes are output-bearing (most types), but `input`
      // is the start of the workflow and shouldn't have outgoing
      // edges because it has no source-handle UI. We don't block
      // it strictly because the executor doesn't care, but we
      // warn so the user understands the visual is non-standard.
      if (sourceNode.type === "output") {
        message.warning("输出节点不应作为连线起点");
        return;
      }
      // Cycle check: would adding this edge create a cycle?
      // BFS from target — if we can reach source, the new edge
      // would close a loop. The executor's BFS terminates on
      // visited nodes, so a cycle would cause infinite retry; the
      // safe path is to reject the edge here.
      if (wouldCreateCycle(nodes, edges, params.source, params.target)) {
        message.warning("不允许成环:连线会形成循环");
        return;
      }
      setEdges((eds) => addEdge(params, eds));
    },
    [setEdges, nodes, edges, message]
  );

  const addNode = (type: string) => {
    const newNode: Node = {
      id: (typeof crypto !== "undefined" && crypto.randomUUID && crypto.randomUUID()) || `n-${Date.now()}`,
      type,
      position: { x: 250, y: nodes.length * 100 + 100 },
      data: { label: `Node ${nodes.length + 1}` },
    };
    if (type === "llm") {
      newNode.data = {
        label: "LLM 节点",
        prompt: "",
        model_name: "",
        temperature: 0.7,
        max_tokens: null,
        system_prompt: "",
        variables: {},
      };
    } else if (type === "code") {
      newNode.data = {
        label: "Code 节点",
        code: "RESULT = 1",
        output_var: "RESULT",
        inputs_mapping: {},
      };
    } else if (type === "tool") {
      newNode.data = {
        label: "Tool 节点",
        tool_id: 0,
        tool_name_cache: "",
        arguments: {},
      };
    } else if (type === "knowledge_retrieval") {
      newNode.data = {
        label: "知识检索节点",
        kb_id: 0,
        kb_name_cache: "",
        query: "",
        top_k: 5,
        score_threshold: 0,
        rerank_enabled: true,
        hybrid_search: true,
      };
    } else if (type === "template_transform") {
      newNode.data = {
        label: "模板转换节点",
        template: "",
      };
    } else if (type === "parameter_extractor") {
      newNode.data = {
        label: "参数抽取节点",
        model_config_id: 0,
        model_name_cache: "",
        input_text: "",
        parameters: [],
        instruction: "请从以下文本中提取参数,以 JSON 格式输出:",
        temperature: 0,
      };
    } else if (type === "question_classifier") {
      newNode.data = {
        label: "问题分类节点",
        model_config_id: 0,
        model_name_cache: "",
        input_text: "",
        categories: [],
        instruction: "请把以下问题分类到最合适的类别,只输出类别 ID:",
        temperature: 0,
      };
    } else if (type === "variable_assigner") {
      newNode.data = {
        label: "变量赋值节点",
        operations: [],
      };
    } else if (type === "variable_aggregator") {
      newNode.data = {
        label: "变量聚合节点",
        aggregation: "collect",
      };
    }
    setNodes((nds) => [...nds, newNode]);
  };

  const onNodeClick = useCallback((_: any, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  const updateNodeData = (nodeId: string, patch: Record<string, any>) => {
    setNodes((nds) =>
      nds.map((node) =>
        node.id === nodeId
          ? { ...node, data: { ...node.data, ...patch } }
          : node
      )
    );
  };

  const handleWorkflowSelect = (workflowId: number, preloaded?: Workflow) => {
    setSelectedWorkflowId(workflowId);
    // Switching workflows invalidates the previous "已保存 X 秒前" hint —
    // the new workflow hasn't been saved (or even seen) by the user yet.
    setSaveStatus("idle");
    setLastSavedAt(null);
    setSaveErrorMsg(null);
    // Caller can supply the workflow object directly to avoid a stale-state
    // race when called immediately after a setWorkflows() that hasn't
    // re-rendered yet.
    const workflow = preloaded ?? workflows.find((w) => w.id === workflowId);
    if (!workflow) {
      return;
    }
    if (workflow.definition) {
      setWorkflowName(workflow.name);
      const loadedNodes: Node[] = workflow.definition.nodes.map((n: any) => {
        const nodeConfig = n.config || {};
        return {
          id: n.id,
          type: n.type,
          position: n.position || { x: 0, y: 0 },
          data: n.data || { label: nodeConfig.label || "Node", ...nodeConfig },
        };
      });
      const loadedEdges: Edge[] = workflow.definition.edges.map((e: any) => ({
        id: e.id,
        source: e.source,
        target: e.target,
      }));
      setNodes(loadedNodes);
      setEdges(loadedEdges);
    }
  };

  // Light client-side graph validation. Returns a human-readable error
  // string or null if the graph is plausible. The backend re-validates
  // server-side; this exists purely to keep obviously-broken workflows
  // from leaving the canvas.
  const validateGraph = (): string | null => {
    if (nodes.length === 0) {
      return "请至少添加一个节点";
    }
    if (nodes.length > 1 && edges.length === 0) {
      return "工作流缺少连线,无法确定执行顺序";
    }
    const hasStart = nodes.some((n) => n.type === "input" || n.type === "start");
    if (!hasStart) {
      return "工作流必须包含一个 input 或 start 节点";
    }
    const hasEnd = nodes.some((n) => n.type === "output" || n.type === "end");
    if (!hasEnd) {
      return "工作流必须包含一个 output 或 end 节点";
    }
    const nodeIds = new Set(nodes.map((n) => n.id));
    for (const e of edges) {
      if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) {
        return `连线引用了不存在的节点: ${e.source} -> ${e.target}`;
      }
    }
    return null;
  };

  const handleSave = async (opts: { silent?: boolean } = {}) => {
    if (selectedWorkflowId === undefined) {
      message.warning("请先选择一个工作流");
      return;
    }
    const graphError = validateGraph();
    if (graphError) {
      message.error(graphError);
      return;
    }
    // Guard against double-clicks. setSaveStatus("saving") is queued
    // synchronously, so the second call inside the same tick still sees
    // "saving" and bails. Without this, a frantic user clicking twice
    // would fire two PUTs and the second one's response would clobber
    // the first's status.
    if (saveStatus === "saving") {
      return;
    }
    setSaveStatus("saving");
    setSaveErrorMsg(null);
    try {
      const workflow = {
        name: workflowName,
        definition: {
          nodes: nodes.map((n) => ({
            id: n.id,
            type: n.type || "unknown",
            position: n.position,
            // Canonical shape: everything the node needs lives in
            // ``config``. The executor still tolerates a legacy ``data``
            // payload via ``_node_cfg``, but we only send ``config`` here.
            config: n.data,
          })),
          edges: edges.map((e) => ({
            id: e.id,
            source: e.source,
            target: e.target,
            condition: (e as any).condition,
          })),
        },
      };
      await workflowApi.saveDesigner(selectedWorkflowId, workflow);
      setSaveStatus("saved");
      setLastSavedAt(new Date());
      if (!opts.silent) {
        message.success("工作流已保存");
      }
    } catch (error: any) {
      setSaveStatus("error");
      const detail =
        error?.response?.data?.detail ||
        error?.message ||
        "保存失败,请检查后端";
      const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
      setSaveErrorMsg(msg);
      message.error(msg);
      throw error;
    }
  };

  const handleRun = async (inputData: Record<string, any> = {}) => {
    if (selectedWorkflowId === undefined) {
      message.warning("请先选择一个工作流");
      return;
    }
    // Graph-cycle guard (the inline check before open used selectedWorkflow
    // truthiness; keep the same shape — just check workflow has ≥1 node).
    if (nodes.length === 0) {
      message.warning("工作流为空");
      return;
    }

    setRunLoading(true);
    setRunError(null);
    setRunResult(null);
    setRunNodeRuns(null);
    try {
      const res = await workflowApi.run(selectedWorkflowId, inputData);
      const payload = res?.data?.data;
      if (payload?.status === "failed") {
        setRunError(payload?.error_message || "执行失败");
        setRunResult(payload);
        message.error("执行失败");
      } else {
        setRunResult(payload);
        message.success("执行成功");
      }
      // M30c: fetch M30a `WorkflowNodeRun` rows so the RunResultPanel
      // can render the per-node timeline. We use the returned run id
      // (always present after a successful /run). Failure to fetch
      // is non-fatal — the panel falls back to in-memory output_data.
      if (payload?.id) {
        try {
          const nodesRes = await workflowApi.listRunNodes(
            selectedWorkflowId,
            payload.id
          );
          if (nodesRes?.data?.code === 200) {
            setRunNodeRuns(nodesRes.data.data || []);
          }
        } catch {
          // silent — panel falls back to output_data
        }
      }
    } catch (error: any) {
      const detail =
        error?.response?.data?.detail ||
        error?.message ||
        "执行失败,请检查后端日志";
      setRunError(typeof detail === "string" ? detail : JSON.stringify(detail));
      message.error("执行失败");
    } finally {
      setRunLoading(false);
    }
  };

  // The click handler on the "运行" button: decide whether to open the modal
  // or run directly.
  const handleRunClick = () => {
    const vars = collectInputVariables(nodes);
    if (vars.length === 0) {
      void handleRun({});
      return;
    }
    setPendingVariables(vars);
  };

  const handleInputConfirm = (values: Record<string, any>) => {
    setPendingVariables(null);
    void handleRun(values);
  };

  const handleInputCancel = () => {
    setPendingVariables(null);
  };

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) || null,
    [nodes, selectedNodeId]
  );

  // Dispatch to the unified panel registry. Falls back to a simple name+type
  // form for Start/End (and any future unknown type) until a panel is added.
  const PanelComponent = selectedNode
    ? getPanelForType(selectedNode.type ?? "")
    : null;

  // Bridge React Flow's Node shape to the WorkflowNode shape expected by the
  // registered panels. Node config currently lives in `data` (set by
  // updateNodeData), so we mirror it into `config` for the panel.
  const panelNodes = nodes.map((n) => ({
    id: n.id,
    type: n.type as string,
    config: (n.data as Record<string, any>) ?? {},
    position: n.position,
    data: n.data as Record<string, any>,
  }));
  const panelEdges = edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: (e as any).sourceHandle,
    condition: (e as any).condition,
  }));

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      {/* ============================================================
          LEFT SIDEBAR — workflow controls + node library (260px)
          ============================================================ */}
      <div
        style={{
          width: 260,
          borderRight: "1px solid #f0f0f0",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          flexShrink: 0,
        }}
      >
        {/* Workflow controls — always visible at top */}
        <div style={{ padding: "12px 12px 8px", borderBottom: "1px solid #f0f0f0" }}>
          <Space direction="vertical" style={{ width: "100%" }} size="small">
            <Select
              placeholder="选择工作流"
              size="small"
              style={{ width: "100%" }}
              value={selectedWorkflowId}
              onChange={handleWorkflowSelect}
              options={workflows.map((w) => ({ label: w.name, value: w.id }))}
            />
            <Input
              size="small"
              value={workflowName}
              onChange={(e) => setWorkflowName(e.target.value)}
              placeholder="工作流名称"
            />
            <Space style={{ width: "100%" }} size={4}>
              <Button
                icon={<SaveOutlined />}
                type="primary"
                size="small"
                onClick={() => handleSave()}
                loading={saveStatus === "saving"}
                style={{ flex: 1 }}
              >
                {saveStatus === "saving" ? "保存中" : "保存"}
              </Button>
              <Button
                icon={<PlayCircleOutlined />}
                size="small"
                onClick={handleRunClick}
                loading={runLoading}
                style={{ flex: 1 }}
              >
                运行
              </Button>
            </Space>
            {/* Inline save status */}
            {saveStatus !== "idle" && (
              <div style={{ fontSize: 11, minHeight: 16, lineHeight: "16px" }}>
                {saveStatus === "saving" && (
                  <span style={{ color: "#1677ff" }}>⏳ 保存中…</span>
                )}
                {saveStatus === "saved" && lastSavedAt && (
                  <span style={{ color: "#52c41a" }}>✓ 已保存 {formatRelative(lastSavedAt)}</span>
                )}
                {saveStatus === "error" && (
                  <span style={{ color: "#ff4d4f" }}>
                    ✗ 保存失败
                    <Button
                      type="link"
                      size="small"
                      onClick={() => handleSave()}
                      style={{ padding: "0 4px", height: 16, fontSize: 11 }}
                    >
                      重试
                    </Button>
                  </span>
                )}
              </div>
            )}
          </Space>
        </div>

        {/* Node library — scrollable, grouped by category */}
        <div style={{ flex: 1, overflow: "auto", padding: "8px 8px" }}>
          <div style={{ fontSize: 11, color: "#999", marginBottom: 6, paddingLeft: 4 }}>
            点击添加节点
          </div>
          {CATEGORY_ORDER.map((cat) => {
            const items = ALL_NODE_LIB.filter((n) => n.category === cat);
            if (items.length === 0) return null;
            return (
              <Collapse
                key={cat}
                ghost
                defaultActiveKey={cat === "input" || cat === "process" ? [cat] : []}
                style={{ marginBottom: 4 }}
                items={[
                  {
                    key: cat,
                    label: (
                      <span style={{ fontSize: 12, fontWeight: 500 }}>
                        {CATEGORY_LABELS[cat]}
                      </span>
                    ),
                    children: (
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {items.map((item) => (
                          <Tooltip key={item.type} title={item.description} placement="right">
                            <Button
                              size="small"
                              icon={<PlusOutlined />}
                              onClick={() => addNode(item.type)}
                              style={{
                                width: "100%",
                                textAlign: "left",
                                justifyContent: "flex-start",
                                height: 30,
                              }}
                            >
                              <span style={{ marginRight: 4 }}>{item.icon}</span>
                              {item.label}
                            </Button>
                          </Tooltip>
                        ))}
                      </div>
                    ),
                  },
                ]}
              />
            );
          })}
        </div>
      </div>

      {/* ============================================================
          MIDDLE PANEL — selected node properties (380px)
          ============================================================ */}
      <div
        style={{
          width: 380,
          borderRight: "1px solid #f0f0f0",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          flexShrink: 0,
        }}
      >
        {selectedNode ? (
          <>
            {/* Panel header */}
            <div
              style={{
                padding: "10px 14px 8px",
                borderBottom: "1px solid #f0f0f0",
                display: "flex",
                alignItems: "center",
                gap: 8,
                flexShrink: 0,
              }}
            >
              <SettingOutlined style={{ color: "#1677ff" }} />
              <span style={{ fontWeight: 600, fontSize: 14 }}>节点属性</span>
              <Tag style={{ marginLeft: "auto" }}>{selectedNode.type}</Tag>
            </div>

            {/* Panel body — scrollable */}
            <div style={{ flex: 1, overflow: "auto", padding: "10px 14px" }}>
              {PanelComponent ? (
                <PanelComponent
                  node={{
                    id: selectedNode.id,
                    type: selectedNode.type as string,
                    config: (selectedNode.data as Record<string, any>) ?? {},
                    position: selectedNode.position,
                    data: selectedNode.data as Record<string, any>,
                  }}
                  nodes={panelNodes}
                  edges={panelEdges}
                  onChange={(newNode) =>
                    updateNodeData(newNode.id, newNode.config)
                  }
                />
              ) : (
                <Form layout="vertical" size="small">
                  <Form.Item label="节点名称">
                    <Input
                      placeholder="节点名称"
                      value={String(selectedNode.data?.label || "")}
                      onChange={(e) =>
                        updateNodeData(selectedNode.id, { label: e.target.value })
                      }
                    />
                  </Form.Item>
                  <div style={{ fontSize: 12, color: "#888" }}>
                    节点类型: <Tag>{selectedNode.type}</Tag>
                  </div>
                </Form>
              )}
            </div>
          </>
        ) : (
          /* No node selected — show canvas shortcut hint */
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              color: "#bbb",
              padding: 24,
            }}
          >
            <SettingOutlined style={{ fontSize: 32 }} />
            <div style={{ textAlign: "center", fontSize: 13 }}>
              从左侧选择节点类型添加
              <br />
              或点击画布上的节点
              <br />
              以编辑其属性
            </div>
          </div>
        )}
      </div>

      {/* ============================================================
          CANVAS — ReactFlow (flex: 1)
          ============================================================ */}
      <div style={{ flex: 1 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesState}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView
        >
          <Controls />
          <MiniMap />
          <Background />
        </ReactFlow>
      </div>

      {/* Modals */}
      <InputValuesModal
        open={pendingVariables !== null}
        variables={pendingVariables ?? []}
        onCancel={handleInputCancel}
        onConfirm={handleInputConfirm}
      />
      <RunResultPanel
        result={runResult}
        loading={runLoading}
        error={runError}
        nodeRuns={runNodeRuns}
        onClose={() => {
          setRunResult(null);
          setRunError(null);
          setRunNodeRuns(null);
        }}
      />
    </div>
  );
}

export default function WorkflowDesignerPage() {
  return (
    <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
      <WorkflowDesignerPageContent />
    </Suspense>
  );
}
