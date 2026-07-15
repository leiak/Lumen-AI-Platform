"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Select, Alert, Empty, Button, Space } from "antd";
import { PlusOutlined, WarningOutlined } from "@ant-design/icons";
import { modelsApi, ModelConfig } from "@/services/models";
import {
  CreateModelInlineModal,
} from "@/components/workflow/CreateModelInlineModal";

export interface ModelSelectorValue {
  model_config_id: number | null;
  model_name: string;
}

export interface ModelSelectorProps {
  value?: ModelSelectorValue;
  onChange: (v: ModelSelectorValue) => void;
}

const MISSING_VALUE = "__missing__";
const CREATE_VALUE = "__create__";

export function ModelSelector({ value, onChange }: ModelSelectorProps) {
  const [models, setModels] = useState<ModelConfig[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createInitialName, setCreateInitialName] = useState("");
  const [searchText, setSearchText] = useState("");

  const refetch = async () => {
    try {
      const res = await modelsApi.list(1, 100);
      if (res.data.code === 200) {
        setModels(res.data.data);
        setLoadError(null);
      } else {
        setLoadError(res.data.message ?? "加载失败");
      }
    } catch (err: any) {
      setLoadError(err?.message ?? "网络错误");
    }
  };

  useEffect(() => {
    refetch();
  }, []);

  // 自动愈合: 当 value 带 model_config_id 但缺 model_name(老工作流 reload
  // 之前只持久化了 id)时,等 models 加载完反查名字,emit onChange 写回 cfg,
  // 让画布卡不再显示「未配置模型」。只在 is_active=true 的模型上愈合,
  // 失效/被删除的模型保留「⚠️ 原配置已失效」标记。
  // ref 守门保证「同一 id 只 emit 一次」,避免 onChange → setState 重新进 effect。
  const healedFor = useRef<number | null>(null);

  useEffect(() => {
    if (!models) return;
    if (!value || value.model_config_id == null) {
      healedFor.current = null;
      return;
    }
    if (value.model_name) {
      healedFor.current = null;
      return;
    }
    if (healedFor.current === value.model_config_id) return;
    const hit = models.find(
      (m) => m.id === value.model_config_id && m.is_active
    );
    if (!hit) return;
    healedFor.current = value.model_config_id;
    onChange({ model_config_id: hit.id, model_name: hit.model_name });
  }, [models, value?.model_config_id, value?.model_name, value, onChange]);

  const activeModels = useMemo(
    () => (models ?? []).filter((m) => m.is_active),
    [models]
  );

  // Resolve the currently-selected id to one of:
  //   - a real active model id (string of the number)
  //   - the MISSING_VALUE sentinel (id no longer resolves)
  //   - undefined (nothing selected)
  const selectedValue: string | undefined = useMemo(() => {
    if (!value) return undefined;
    if (value.model_config_id == null) return undefined;
    const hit = activeModels.find((m) => m.id === value.model_config_id);
    return hit ? String(hit.id) : MISSING_VALUE;
  }, [value, activeModels]);

  const displayMissingLabel = value?.model_name
    ? `⚠️ (已删除) ${value.model_name}`
    : "⚠️ (已删除)";

  const options = useMemo(() => {
    const opts = activeModels.map((m) => ({
      label: m.name,
      value: String(m.id),
    }));
    if (selectedValue === MISSING_VALUE) {
      opts.push({ label: displayMissingLabel, value: MISSING_VALUE });
    }
    return opts;
  }, [activeModels, selectedValue, displayMissingLabel]);

  const handleChange = (v: string) => {
    if (v === MISSING_VALUE) {
      // User re-clicked the missing sentinel — open create modal
      // pre-filled with the original model_name so they can rebuild it.
      setCreateInitialName(value?.model_name ?? "");
      setCreateOpen(true);
      return;
    }
    const m = activeModels.find((x) => x.id === Number(v));
    if (!m) return;
    onChange({ model_config_id: m.id, model_name: m.model_name });
  };

  const handleSearch = (text: string) => {
    setSearchText(text);
  };

  const handleCreateClick = () => {
    setCreateInitialName(searchText || value?.model_name || "");
    setCreateOpen(true);
  };

  const handleCreated = async (created: ModelConfig) => {
    setCreateOpen(false);
    await refetch();
    onChange({ model_config_id: created.id, model_name: created.model_name });
  };

  const dropdownRender = (menu: React.ReactNode) => (
    <div>
      {menu}
      <div style={{ padding: 8, borderTop: "1px solid #f0f0f0" }}>
        <Button
          type="link"
          icon={<PlusOutlined />}
          onClick={handleCreateClick}
          style={{ padding: 0 }}
        >
          {searchText
            ? `新建模型 "${searchText}"`
            : "新建模型"}
        </Button>
      </div>
    </div>
  );

  if (loadError) {
    return (
      <Space direction="vertical" style={{ width: "100%" }}>
        <Alert
          type="error"
          showIcon
          message="模型管理数据加载失败,请刷新重试"
          description={loadError}
        />
      </Space>
    );
  }

  if (models !== null && activeModels.length === 0 && selectedValue !== MISSING_VALUE) {
    return (
      <Empty
        description={
          <span>
            尚未配置任何模型,请前往
            <a href="/dashboard/system/models" target="_blank" rel="noreferrer">
              模型管理
            </a>
            添加
          </span>
        }
      />
    );
  }

  return (
    <>
      <Select
        showSearch
        allowClear
        placeholder="选择模型"
        value={selectedValue}
        options={options}
        onChange={handleChange}
        onSearch={handleSearch}
        onClear={() => onChange({ model_config_id: null, model_name: "" })}
        dropdownRender={dropdownRender}
        filterOption={(input, option) =>
          (option?.label ?? "").toString().toLowerCase().includes(input.toLowerCase())
        }
        style={{ width: "100%" }}
        optionLabelProp="label"
      />
      {selectedValue === MISSING_VALUE && (
        <div
          style={{
            marginTop: 6,
            padding: "4px 8px",
            background: "#fffbe6",
            border: "1px solid #ffe58f",
            borderRadius: 4,
            color: "#ad6800",
            fontSize: 12,
          }}
        >
          <WarningOutlined style={{ marginRight: 4 }} />
          该节点引用的模型配置已删除或被禁用,点击下拉里的"⚠️ 原配置已失效"项可重新选择或重建。
        </div>
      )}
      <CreateModelInlineModal
        open={createOpen}
        initialModelName={createInitialName}
        onCancel={() => setCreateOpen(false)}
        onCreated={handleCreated}
      />
    </>
  );
}

export default ModelSelector;
