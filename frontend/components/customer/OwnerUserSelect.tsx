"use client";
// frontend/components/customer/OwnerUserSelect.tsx
//
// 客户 / 任务 owner 选择器 —— 复用了 ``/api/v1/users/assignable`` 端点
// (同租户 active 用户,任何已认证用户可调,无 superuser 限制)。
//
// 模式参考 ``components/EmbeddingModelSelect.tsx``:
//   - 列表 < 50 行 → ``virtual={false}``(防 AntD rc-virtual-list 把非
//     active option 吞掉,MEMORY 2026-06-08 踩过)。
//   - ``optionFilterProp="label"`` 让 showSearch 按组合 label 过滤
//     (full_name + username + email,确保"按用户名搜"能命中)。
//   - ``onLoaded`` 回调把列表暴露给父组件,父组件用它做"自动选当前
//     用户"的默认行为(用户开 modal 那一刻没默认值 → 列表就绪后
//     推入 form field)。
import { useEffect } from "react";
import { Alert, Select, Tag } from "antd";
import { useQuery } from "@tanstack/react-query";
import { usersApi, type UserSimple } from "@/services/users";

interface Props {
  value?: number;
  onChange?: (val: number) => void;
  disabled?: boolean;
  /**
   * Fires once the assignable-user list has loaded. Parent uses this
   * to push the current user's id into its form (default-owner flow
   * per spec §5.2). The parent should only set the field when it's
   * currently empty so a user who already picked an owner doesn't
   * get silently overwritten.
   */
  onLoaded?: (users: UserSimple[]) => void;
}

/** 把 ``UserSimple`` 拼成 AntD option 用的 label,showSearch 时按它过滤。 */
function makeLabel(u: UserSimple): string {
  const parts: string[] = [];
  if (u.full_name) parts.push(u.full_name);
  parts.push(u.username);
  if (u.email) parts.push(u.email);
  return parts.join(" ");
}

export default function OwnerUserSelect({
  value,
  onChange,
  disabled,
  onLoaded,
}: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["users", "assignable"],
    queryFn: () => usersApi.assignable(1, 100),
    staleTime: 5 * 60_000, // 5min — user 列表 1 个 session 内不会变
  });

  useEffect(() => {
    if (onLoaded && data?.items) {
      onLoaded(data.items);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const list = data?.items ?? [];
  const hasNoUsers = !isLoading && list.length === 0;

  const options = list.map((u) => ({
    value: u.id,
    label: makeLabel(u),
    // pass through for optionRender JSX
    full_name: u.full_name ?? null,
    username: u.username,
    email: u.email,
  }));

  return (
    <div>
      <Select
        value={value}
        onChange={onChange}
        disabled={disabled || isLoading}
        loading={isLoading}
        placeholder={hasNoUsers ? "暂无可指派用户" : "选择负责人"}
        showSearch
        optionFilterProp="label"
        options={options}
        // 用户数典型 5 ~ 50,远低于 virtual 阈值;且 custom optionRender
        // + virtual=true 会丢 option(见 MEMORY 2026-06-08)。
        virtual={false}
        style={{ width: "100%" }}
        optionRender={(option) => {
          const o = option.data as {
            full_name: string | null;
            username: string;
            email: string;
          };
          return (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 8,
              }}
            >
              <span
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {o.full_name || o.username}
                {o.full_name && (
                  <span style={{ color: "#999", marginLeft: 6 }}>
                    ({o.username})
                  </span>
                )}
              </span>
              <span style={{ color: "#bbb", fontSize: 12, flexShrink: 0 }}>
                #{o.email}
              </span>
            </div>
          );
        }}
      />
      {error && (
        <Alert
          type="error"
          showIcon
          style={{ marginTop: 8 }}
          message="加载用户列表失败"
          description="请检查网络或稍后重试。"
        />
      )}
      {hasNoUsers && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 8 }}
          message="暂无可指派用户"
          description="同租户内没有 active 用户。请联系管理员添加用户。"
        />
      )}
    </div>
  );
}
