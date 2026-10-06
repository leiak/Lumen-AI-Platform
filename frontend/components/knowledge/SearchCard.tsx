"use client";

import {
  Card,
  Input,
  Collapse,
  Slider,
  Switch,
  Space,
  Button,
  Divider,
  List,
  Tag,
  Typography,
} from "antd";
import {
  SettingOutlined,
  SearchOutlined,
  FileTextOutlined,
} from "@ant-design/icons";

import type { SearchResult } from "@/app/dashboard/knowledge/hooks/useDocumentSearch";

const { TextArea } = Input;
const { Text } = Typography;
const { Panel } = Collapse;

interface SearchCardProps {
  // query input
  searchQuery: string;
  setSearchQuery: (v: string) => void;

  // advanced options
  searchOptions: {
    k: number;
    alpha: number;
    rerank: boolean;
    rerankTopN: number;
    fieldWeights: string;
  };
  setSearchOptions: (v: {
    k: number;
    alpha: number;
    rerank: boolean;
    rerankTopN: number;
    fieldWeights: string;
  }) => void;

  // search execution
  searching: boolean;
  searchResults: SearchResult[];

  // handlers
  handleSearch: () => Promise<void>;
  showDetail: (result: SearchResult) => void;
}

/**
 * 「文档搜索」Card —— 从 page.tsx 抽出。
 *
 * 由 useDocumentSearch hook 持有 query / options / results / 全部 setter。
 * 包含搜索输入框 / 高级选项 collapse / 搜索按钮 / 结果列表 + 「未找到」hint。
 *
 * 不包含 detail modal(留 page 层,因为跟搜索结果选 item 配合简单 Modal 31 行)。
 */
export default function SearchCard({
  searchQuery,
  setSearchQuery,
  searchOptions,
  setSearchOptions,
  searching,
  searchResults,
  handleSearch,
  showDetail,
}: SearchCardProps) {
  return (
    <Card title="文档搜索">
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <TextArea
          placeholder="输入搜索内容..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onPressEnter={(e) => {
            e.preventDefault();
            handleSearch();
          }}
          rows={3}
        />

        <Collapse ghost>
          <Panel
            header={
              <Space>
                <SettingOutlined />
                高级选项
              </Space>
            }
            key="advanced"
          >
            <Space direction="vertical" style={{ width: "100%" }} size="small">
              <div>
                <Text>返回数量 (k): {searchOptions.k}</Text>
                <Slider
                  min={1}
                  max={50}
                  value={searchOptions.k}
                  onChange={(value) =>
                    setSearchOptions({ ...searchOptions, k: value })
                  }
                />
              </div>
              <div>
                <Text>向量权重 (alpha): {searchOptions.alpha.toFixed(2)}</Text>
                <Slider
                  min={0}
                  max={1}
                  step={0.1}
                  value={searchOptions.alpha}
                  onChange={(value) =>
                    setSearchOptions({ ...searchOptions, alpha: value })
                  }
                />
              </div>
              <div>
                <Space>
                  <Switch
                    size="small"
                    checked={searchOptions.rerank}
                    onChange={(checked) =>
                      setSearchOptions({ ...searchOptions, rerank: checked })
                    }
                  />
                  <Text>启用重排 (Rerank)</Text>
                </Space>
              </div>
              {searchOptions.rerank && (
                <div>
                  <Text>重排候选数: {searchOptions.rerankTopN}</Text>
                  <Slider
                    min={5}
                    max={50}
                    value={searchOptions.rerankTopN}
                    onChange={(value) =>
                      setSearchOptions({ ...searchOptions, rerankTopN: value })
                    }
                  />
                </div>
              )}
            </Space>
          </Panel>
        </Collapse>

        <Button
          type="primary"
          icon={<SearchOutlined />}
          onClick={handleSearch}
          loading={searching}
        >
          搜索
        </Button>
      </Space>

      {/* Search Results */}
      {searchResults.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <Divider orientation="left">
            找到 {searchResults.length} 条相关结果
          </Divider>
          <List
            size="small"
            dataSource={searchResults}
            style={{ maxHeight: 400, overflow: "auto" }}
            renderItem={(item) => (
              <List.Item
                style={{ cursor: "pointer" }}
                onClick={() => showDetail(item)}
              >
                <List.Item.Meta
                  avatar={<FileTextOutlined />}
                  title={
                    <Text ellipsis style={{ maxWidth: 600 }}>
                      {item.text}
                    </Text>
                  }
                  description={
                    <Space size="small">
                      <Tag>距离: {item.distance.toFixed(4)}</Tag>
                      <Tag>Chunk: {item.metadata.chunk_id}</Tag>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        </div>
      )}

      {searchResults.length === 0 && searchQuery && !searching && (
        <Text type="secondary" style={{ marginTop: 16, display: "block" }}>
          未找到相关结果
        </Text>
      )}
    </Card>
  );
}