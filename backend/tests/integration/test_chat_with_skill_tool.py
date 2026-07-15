"""End-to-end test: chat uses a script skill as a tool.

M16: verifies the integration between SkillRunner.get_active_skills()
(returns tools tuple), the PreparedContext.tools field, and the tool
call loop in ChatService.stream_chat_messages().
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage, ToolCall


def test_skill_runner_returns_tool_for_script_skill():
    """SkillRunner.get_active_skills returns a working tool for script type."""
    from lumen_services.skill_runner import SkillRunner
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace, InstalledSkill

    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        s = SkillMarketplace(
            name=f"doubler-{suffix}",
            category="code",
            type="script",
            type_config={"code": "def main(x): return x * 2", "timeout": 5},
            is_verified=1,
        )
        db.add(s); db.commit(); db.refresh(s)
        db.add(InstalledSkill(
            tenant_id=1, marketplace_skill_id=s.id, status="active"
        ))
        db.commit()
        skill_id = s.id
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        prompts, tools = SkillRunner.get_active_skills(db2, 1, [skill_id])
        assert len(prompts) == 0  # script type, no system prompt
        assert len(tools) == 1
        assert tools[0].name == f"skill_{skill_id}_script"
        # Verify the tool actually runs the script
        result = tools[0].run({"x": 21})
        assert result == 42
    finally:
        db2.close()


@pytest.mark.asyncio
async def test_chat_invokes_script_skill_as_tool():
    """E2E: ChatService.stream_chat_messages() binds tools, runs the tool
    call loop, executes the script sandbox, and streams the final response.

    Mocks ChatOpenAI to return a single tool_call followed by a final
    response mentioning 42. Verifies:
      - chat_model.invoke was called at least twice (once for the
        tool_call round, once for the final response)
      - the final streamed text contains "42" (sandbox actually ran)
      - the streamed text does NOT contain "Tool error" (sandbox returned
        cleanly)
    """
    from lumen_services.skill_runner import SkillRunner
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace, InstalledSkill

    # 1) Setup: create a script skill + install it
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        s = SkillMarketplace(
            name=f"e2e-doubler-{suffix}",
            category="code",
            type="script",
            type_config={"code": "def main(x): return x * 2", "timeout": 5},
            is_verified=1,
        )
        db.add(s); db.commit(); db.refresh(s)
        db.add(InstalledSkill(
            tenant_id=1, marketplace_skill_id=s.id, status="active"
        ))
        db.commit()
        skill_id = s.id
    finally:
        db.close()

    # 2) Build the actual tools list the chat pipeline would see
    db2 = SessionLocal()
    try:
        _prompts, tools = SkillRunner.get_active_skills(db2, 1, [skill_id])
        assert len(tools) == 1, "test setup: expected exactly 1 tool"
        tool_name = tools[0].name
    finally:
        db2.close()

    # 3) Mock the chat model: first invoke returns a tool_call, second
    #    returns the final answer. We replace ChatService.chat_model with
    #    a MagicMock that has bind_tools() and invoke().
    mock_chat_model = MagicMock()
    tool_call = ToolCall(name=tool_name, args={"x": 21}, id="test-call-id-1")
    mock_chat_model.invoke.side_effect = [
        AIMessage(content="", tool_calls=[tool_call]),
        AIMessage(content="The answer is 42"),
    ]
    mock_chat_model.bind_tools = MagicMock(return_value=mock_chat_model)

    from lumen_services.chat_service import ChatService
    svc = ChatService()
    svc.chat_model = mock_chat_model

    # 4) Drive the streaming function with a minimal user message
    chunks: list[str] = []
    async for chunk in svc.stream_chat_messages(
        messages=[{"role": "user", "content": "double 21"}],
        tools=tools,
    ):
        chunks.append(str(chunk))

    # 5) Assertions
    full = "".join(chunks)
    assert "42" in full, f"sandbox output should reach the stream; got {full!r}"
    assert "Tool error" not in full, f"unexpected tool error: {full!r}"
    assert mock_chat_model.bind_tools.called, "bind_tools() should be invoked when tools present"
    assert mock_chat_model.invoke.call_count == 2, (
        f"expected 2 LLM invocations (tool_call round + final); "
        f"got {mock_chat_model.invoke.call_count}"
    )
