// frontend/components/workflow/designer/InputValuesModal.tsx
// Collects values for the input node's `variables` before running a workflow.
// Backend contract: POST /api/v1/workflows/{id}/run body is
// { input_data: {<var_name>: <value> } }, executor stores as
// pool.add(["input", k], v) (see backend/app/services/workflow_executor.py:65-69).
import { useEffect } from "react";
import { Modal, Form, Input, InputNumber, Select, Space, Typography } from "antd";

// Mirror of InputVariable in components/workflow/nodes/input/types.ts.
export interface InputVarSpec {
  name: string;
  type: "string" | "number" | "boolean" | "object" | "array";
  required?: boolean;
}

export interface InputValuesModalProps {
  open: boolean;
  variables: InputVarSpec[];
  onCancel: () => void;
  // Receives a record {<var_name>: <value>} — the payload for input_data.
  onConfirm: (values: Record<string, any>) => void;
}

// Returns the AntD input element matching `spec.type`. Inlined in the
// JSX below (not as a child of <Form.Item>) because AntD's Form.Item uses
// `React.cloneElement` on its direct child to inject `id`/`value`/
// `onChange`/ref — wrapping the input in a custom component breaks
// those injections. Keeping this helper as a JSX factory preserves the
// spec's type-switch structure while letting Form.Item reach the input.
function renderFieldFor(spec: InputVarSpec) {
  if (spec.type === "number") {
    return <InputNumber style={{ width: "100%" }} placeholder="number" />;
  }
  if (spec.type === "boolean") {
    return (
      <Select
        options={[
          { value: true, label: "true" },
          { value: false, label: "false" },
        ]}
        placeholder="boolean"
        style={{ width: "100%" }}
      />
    );
  }
  // string (default) and object/array
  return <Input placeholder={spec.type} />;
}

export function InputValuesModal({
  open,
  variables,
  onCancel,
  onConfirm,
}: InputValuesModalProps) {
  const [form] = Form.useForm();

  // Reset whenever the modal opens so previous values don't leak.
  useEffect(() => {
    if (open) form.resetFields();
  }, [open, form]);

  if (variables.length === 0) {
    // No inputs to collect — close immediately via onCancel. (Caller should
    // normally skip rendering the modal in this case; this is defensive.)
    return null;
  }

  return (
    <Modal
      open={open}
      title="提供输入变量"
      onCancel={onCancel}
      onOk={async () => {
        const raw = await form.validateFields().catch(() => null);
        if (!raw) return;
        // Coerce object/array JSON strings back to structured values.
        const out: Record<string, any> = {};
        for (const v of variables) {
          const val = raw[v.name];
          if (val === undefined || val === "") {
            if (v.required) {
              // validateFields would have already rejected; double-check.
              return;
            }
            out[v.name] = null;
            continue;
          }
          if ((v.type === "object" || v.type === "array") && typeof val === "string") {
            try {
              out[v.name] = JSON.parse(val);
            } catch {
              out[v.name] = val; // fall back to raw string
            }
          } else {
            out[v.name] = val;
          }
        }
        onConfirm(out);
      }}
      okText="确定"
      cancelText="取消"
      destroyOnHidden
    >
      <Space direction="vertical" style={{ width: "100%" }}>
        <Typography.Text type="secondary">
          请填写本工作流输入节点声明的变量,值会作为 input_data 传给后端执行。
        </Typography.Text>
        <Form form={form} layout="vertical">
          {variables.map((v) => (
            <Form.Item
              key={v.name}
              name={v.name}
              label={v.name}
              rules={
                v.required
                  ? [{ required: true, message: `${v.name} 必填` }]
                  : []
              }
            >
              {renderFieldFor(v)}
            </Form.Item>
          ))}
        </Form>
      </Space>
    </Modal>
  );
}
