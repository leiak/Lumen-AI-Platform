"use client";
import { Component, ReactNode } from "react";
import { Result, Button } from "antd";

interface State { hasError: boolean; message?: string }

export class ErrorBoundary extends Component<{ children: ReactNode; onRetry?: () => void }, State> {
  state: State = { hasError: false };
  static getDerivedStateFromError(err: Error): State { return { hasError: true, message: err.message }; }
  componentDidCatch() { /* swallow; UI 已展示 */ }
  render() {
    if (this.state.hasError) {
      return (
        <Result
          status="error"
          title="加载失败"
          subTitle={this.state.message ?? "请稍后重试"}
          extra={<Button onClick={() => { this.setState({ hasError: false }); this.props.onRetry?.(); }}>重试</Button>}
        />
      );
    }
    return this.props.children;
  }
}
