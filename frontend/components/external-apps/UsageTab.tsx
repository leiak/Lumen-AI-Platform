"use client";

import { useEffect, useState } from "react";
import { Card, Statistic, Row, Col, Spin } from "antd";
import { externalAppApi } from "@/services/externalApp";
import type { ExternalAppUsage } from "@/types/api";

export default function UsageTab({ appId }: { appId: number }) {
  const [data, setData] = useState<ExternalAppUsage | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    externalAppApi
      .usage(appId)
      .then((d) => {
        if (mounted) setData(d);
      })
      .catch(() => {
        if (mounted) setData(null);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [appId]);

  if (loading) return <Spin />;
  if (!data) return null;
  return (
    <div>
      <Row gutter={16}>
        <Col span={6}>
          <Card>
            <Statistic title="总对话数" value={data.total_conversations} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="7 日活跃访客" value={data.active_visitors_7d} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="7 日 token 签发" value={data.token_issues_7d} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="最后使用"
              value={
                data.last_used_at
                  ? new Date(data.last_used_at).toLocaleString()
                  : "—"
              }
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
