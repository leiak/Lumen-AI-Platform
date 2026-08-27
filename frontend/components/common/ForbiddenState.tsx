// M38.2.x v2: inline 403 "无权限" 提示组件。
//
// 用途:列表 / 详情页遇到 permission_denied 时,inline 显示
// 「您无权访问 — 请联系 workspace owner 申请权限」,而不是返回空白
// 或纯 alert。AntD Empty + LockOutlined icon。

"use client";

import React from "react";
import { Empty, Card } from "antd";
import { LockOutlined } from "@ant-design/icons";

export interface ForbiddenStateProps {
  /** 给前端 dev 看,后端实际返的 permission token(例 "kb.update")。 */
  permission?: string;
  /** 提示 owner 的话术,默认走中文。 */
  message?: string;
}

export function ForbiddenState({
  permission,
  message,
}: ForbiddenStateProps): React.ReactElement {
  const desc = message ?? (
    permission
      ? `您无权访问 — 缺少权限 ${permission},请联系 workspace owner 申请。`
      : "您无权访问此资源,请联系 workspace owner 申请权限。"
  );
  return (
    <Card variant="borderless" style={{ marginTop: 16 }}>
      <Empty
        image={
          <LockOutlined
            style={{ fontSize: 64, color: "rgba(0,0,0,0.25)" }}
          />
        }
        imageStyle={{ height: 80 }}
        description={<span>{desc}</span>}
      />
    </Card>
  );
}