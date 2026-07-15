"""HTTP caller for M16 http skills: allowlist + SSRF + env credentials."""
import fnmatch
import ipaddress
import json
import os
import socket
from urllib.parse import urlparse
import httpx
from lumen_core.skill_errors import SkillSecurityError, SkillExecutionError
from lumen_schemas.skill import HttpTypeConfig


# RFC 1918 + loopback + link-local + IPv6 equivalents
FORBIDDEN_CIDRS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _resolve_host_to_ip(host: str) -> str:
    try:
        return socket.gethostbyname(host)
    except (socket.gaierror, UnicodeError) as e:
        raise SkillSecurityError(f"Cannot resolve host: {host}: {e}")


def _is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise SkillSecurityError("URL has no host")
    if parsed.scheme not in ("http", "https"):
        raise SkillSecurityError(f"URL scheme must be http/https: {parsed.scheme}")
    ip = ipaddress.ip_address(_resolve_host_to_ip(host))
    for cidr in FORBIDDEN_CIDRS:
        if ip in cidr:
            raise SkillSecurityError(
                f"URL host {host} resolves to internal IP {ip} (blocked)"
            )
    return True


def _is_allowlisted(url: str, allowed_domains: list) -> bool:
    host = urlparse(url).hostname
    for pattern in allowed_domains:
        if fnmatch.fnmatch(host, pattern):
            return True
    return False


def _resolve_env_ref(ref: str) -> str:
    if not (ref.startswith("${") and ref.endswith("}") and len(ref) > 3):
        raise SkillSecurityError(f"credential_ref must be ${{ENV_VAR}} format: {ref}")
    env_name = ref[2:-1]
    value = os.environ.get(env_name)
    if not value:
        raise SkillSecurityError(f"Environment variable not set: {env_name}")
    return value


def _build_auth_header(auth) -> dict:
    if auth.type == "bearer":
        token = _resolve_env_ref(auth.credential_ref)
        return {"Authorization": f"Bearer {token}"}
    if auth.type == "api_key":
        key = _resolve_env_ref(auth.credential_ref)
        return {"X-API-Key": key}
    if auth.type == "basic":
        token = _resolve_env_ref(auth.credential_ref)
        return {"Authorization": f"Basic {token}"}
    raise SkillExecutionError(f"Unknown auth type: {auth.type}")


def _render_body(template: str, args: dict) -> dict:
    """Substitute {{arg_name}} placeholders with values from args."""
    rendered = template
    for k, v in args.items():
        rendered = rendered.replace("{{" + k + "}}", str(v))
    return json.loads(rendered)


class HttpCaller:
    @staticmethod
    def execute(
        config: HttpTypeConfig,
        input_args: dict,
        allowed_domains: list,
    ) -> str:
        # 1. SSRF + scheme check
        _is_safe_url(config.url)

        # 2. Allowlist check
        if not _is_allowlisted(config.url, allowed_domains):
            raise SkillSecurityError(
                f"Host {urlparse(config.url).hostname} not in allowlist"
            )

        # 3. Build headers (auth first, then user headers can override)
        headers = {}
        if config.auth:
            headers.update(_build_auth_header(config.auth))
        headers.update(config.headers)

        # 4. Make the request
        try:
            with httpx.Client(timeout=config.timeout) as client:
                if config.method == "GET":
                    resp = client.get(config.url, headers=headers)
                elif config.method == "POST":
                    body = _render_body(config.body_template, input_args) if config.body_template else None
                    resp = client.post(config.url, headers=headers, json=body)
                elif config.method == "PUT":
                    body = _render_body(config.body_template, input_args) if config.body_template else None
                    resp = client.put(config.url, headers=headers, json=body)
                elif config.method == "PATCH":
                    body = _render_body(config.body_template, input_args) if config.body_template else None
                    resp = client.patch(config.url, headers=headers, json=body)
                elif config.method == "DELETE":
                    resp = client.delete(config.url, headers=headers)
                else:
                    raise SkillExecutionError(f"Unsupported method: {config.method}")
        except httpx.TimeoutException:
            raise SkillExecutionError(f"HTTP request timed out after {config.timeout}s")

        # 5. Return body
        if resp.status_code >= 400:
            raise SkillExecutionError(
                f"HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return resp.text
