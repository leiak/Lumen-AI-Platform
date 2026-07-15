export interface WorkflowNode {
  id: string;
  type: 'input' | 'agent' | 'condition' | 'action' | 'output';
  position: { x: number; y: number };
  data: {
    label: string;
    agent_id?: number;
    condition?: string;
    action_type?: string;
  };
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
}

export interface Workflow {
  id: number;
  name: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}