"""Tests for type_config Pydantic schemas (M16)."""
import pytest
from pydantic import ValidationError


def test_script_type_config_minimal():
    from lumen_schemas.skill import ScriptTypeConfig
    cfg = ScriptTypeConfig(code="print(1)")
    assert cfg.code == "print(1)"
    assert cfg.runtime == "python-3.11"
    assert cfg.timeout == 30
    assert cfg.input_schema is None
    assert cfg.output_schema is None


def test_script_type_config_full():
    from lumen_schemas.skill import ScriptTypeConfig
    cfg = ScriptTypeConfig(
        code="def main(x): return x",
        runtime="python-3.11",
        timeout=60,
        input_schema={"type": "object", "properties": {"x": {"type": "number"}}},
        output_schema={"type": "object"},
    )
    assert cfg.timeout == 60
    assert cfg.input_schema["properties"]["x"]["type"] == "number"


def test_script_type_config_rejects_bad_timeout():
    from lumen_schemas.skill import ScriptTypeConfig
    with pytest.raises(ValidationError):
        ScriptTypeConfig(code="x", timeout=0)  # too low
    with pytest.raises(ValidationError):
        ScriptTypeConfig(code="x", timeout=121)  # too high


def test_http_type_config_minimal():
    from lumen_schemas.skill import HttpTypeConfig
    cfg = HttpTypeConfig(url="https://api.example.com/v1")
    assert cfg.method == "GET"
    assert cfg.timeout == 30
    assert cfg.headers == {}
    assert cfg.body_template is None
    assert cfg.auth is None


def test_http_type_config_rejects_bad_method():
    from lumen_schemas.skill import HttpTypeConfig
    with pytest.raises(ValidationError):
        HttpTypeConfig(url="https://x.com", method="OPTIONS")


def test_http_auth_must_use_env_var_format():
    from lumen_schemas.skill import HttpAuth
    # Good format
    auth = HttpAuth(type="bearer", credential_ref="${MY_KEY}")
    assert auth.credential_ref == "${MY_KEY}"
    # Bad format — must be ${...}
    with pytest.raises(ValidationError):
        HttpAuth(type="bearer", credential_ref="plaintext-key")


# === M17: Upsert + TestRun schema tests ===

def test_skill_upsert_request_accepts_all_5_types():
    from lumen_schemas.skill import SkillUpsertRequest
    for t in ["prompt", "script", "http", "knowledge_retrieval", "tool"]:
        req = SkillUpsertRequest(
            name=f"test-{t}", category="code", type=t,
            content="x" if t == "prompt" else None,
            type_config={"foo": "bar"} if t != "prompt" else None,
        )
        assert req.type == t


def test_skill_upsert_request_rejects_unknown_type():
    from lumen_schemas.skill import SkillUpsertRequest
    with pytest.raises(ValidationError):
        SkillUpsertRequest(name="x", category="code", type="future_type")


def test_skill_test_run_request_and_result_round_trip():
    from lumen_schemas.skill import SkillTestRunRequest, SkillTestRunResult
    req = SkillTestRunRequest(input_args={"x": 5})
    assert req.input_args == {"x": 5}

    result = SkillTestRunResult(
        result={"answer": 10}, latency_ms=42, type="script",
    )
    assert result.result == {"answer": 10}
    assert result.latency_ms == 42
    assert result.error is None
    assert result.type == "script"
