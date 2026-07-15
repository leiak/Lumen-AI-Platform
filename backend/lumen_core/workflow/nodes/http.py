"""HTTPNode — 完整 HTTP 客户端(method/headers/body/auth/timeout/SSL)。

所有错误由 run_node_with_handling(error_strategy=...) 兜底,
节点只关心 happy path,4xx/5xx → 抛 httpx.HTTPStatusError,网络错 → 抛 httpx.RequestError。
"""
import base64
import json
from typing import Any, Literal

import httpx
from pydantic import ConfigDict, Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.template_parser import VariableTemplateParser
from lumen_core.workflow.types import SegmentType

BodyType = Literal["none", "json", "form", "raw"]
AuthType = Literal["none", "bearer", "basic", "api_key", "custom_header"]


class HTTPNodeData(BaseNodeData):
    model_config = ConfigDict(extra="ignore")
    method: str = "GET"  # Plain str so runtime "if not d.method" check can fire on ""
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    body_type: BodyType = "none"
    body: str | dict = ""
    auth_type: AuthType = "none"
    auth_config: dict[str, str] = Field(default_factory=dict)
    verify_ssl: bool = True
    follow_redirects: bool = True


class HTTPNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        return HTTPNodeData.model_validate(
            {**config, "version": config.get("version", "1")}
        )

    def outputs(self) -> list[OutputVar]:
        """Declare the 4 outputs exposed by HTTPNode.

        NOTE: ``body`` is declared as OBJECT for consistency with the common
        JSON-response case, but at runtime it may be a plain string when the
        response is not valid JSON. Downstream nodes that template-interpolate
        body (e.g. via {{#http_1.body#}}) will get the string representation
        either way; nodes that index into body assume the JSON-parsed dict
        shape.
        """
        return [
            OutputVar(name="status_code", type=SegmentType.NUMBER, description="HTTP 状态码"),
            OutputVar(name="headers", type=SegmentType.OBJECT, description="响应头"),
            OutputVar(name="body", type=SegmentType.OBJECT, description="响应 body (JSON 解析后或纯文本字符串)"),
            OutputVar(name="error", type=SegmentType.STRING, description="错误信息"),
        ]

    def _render_url(self) -> str:
        assert isinstance(self._data, HTTPNodeData)
        return VariableTemplateParser(self._data.url).format(self.pool)

    def _build_auth_headers(self, base: dict[str, str]) -> dict[str, str]:
        """Inject auth headers based on ``auth_type``.

        NOTE: ``auth_config`` values are NOT rendered through
        VariableTemplateParser by design — secrets should live in
        explicit credential storage (model_configs, etc.) rather than
        the workflow VariablePool. If you need a runtime-injected secret,
        use a Tool node + parameter-passing instead.
        """
        assert isinstance(self._data, HTTPNodeData)
        d = self._data
        if d.auth_type == "bearer":
            base["Authorization"] = f"Bearer {d.auth_config.get('token', '')}"
        elif d.auth_type == "basic":
            user = d.auth_config.get("username", "")
            pwd = d.auth_config.get("password", "")
            base["Authorization"] = "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()
        elif d.auth_type == "api_key":
            base[d.auth_config.get("header_name", "X-API-Key")] = d.auth_config.get("api_key", "")
        elif d.auth_type == "custom_header":
            base.update(d.auth_config)
        return base

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, HTTPNodeData)
        d = self._data
        if not d.url:
            raise ValueError("URL 不能为空")
        if not d.method:
            raise ValueError("HTTP method 不能为空")

        url = self._render_url()
        headers = {
            k: VariableTemplateParser(v).format(self.pool) for k, v in d.headers.items()
        }
        params = {
            k: VariableTemplateParser(v).format(self.pool) for k, v in d.query_params.items()
        }
        headers = self._build_auth_headers(headers)

        # Build the kwargs to pass into httpx based on body_type so that httpx
        # owns the Content-Type / encoding contract for json= and data= bodies.
        request_kwargs: dict[str, Any] = {
            "method": d.method,
            "url": url,
            "headers": headers,
            "params": params,
        }

        if d.body_type == "json":
            # JSON body — let httpx serialize + set Content-Type
            if isinstance(d.body, str):
                parsed_body = json.loads(d.body) if d.body.strip() else None
            else:
                parsed_body = d.body
            if parsed_body is not None:
                request_kwargs["json"] = parsed_body
        elif d.body_type == "form":
            # Form body — httpx URL-encodes dict + sets Content-Type
            if isinstance(d.body, dict):
                request_kwargs["data"] = d.body
            elif isinstance(d.body, str) and d.body:
                # String form body: render template + pass as raw content (user-encoded)
                request_kwargs["content"] = VariableTemplateParser(d.body).format(self.pool)
        elif d.body_type == "raw":
            # Raw body — pass through as content (with template rendering for strings)
            if isinstance(d.body, str):
                request_kwargs["content"] = VariableTemplateParser(d.body).format(self.pool)
            elif isinstance(d.body, dict):
                # Unusual but allowed — serialize as JSON content (caller's choice)
                request_kwargs["content"] = json.dumps(d.body)
        # body_type == "none" — no body kwarg

        async with httpx.AsyncClient(
            verify=d.verify_ssl, follow_redirects=d.follow_redirects
        ) as client:
            resp = await client.request(**request_kwargs)

        try:
            parsed = resp.json()
        except Exception:
            parsed = resp.text

        return NodeRunResult(
            node_id=self.node_id,
            output_values={
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
                "body": parsed,
                "error": None,
            },
        )
