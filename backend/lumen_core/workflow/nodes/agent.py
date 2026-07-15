"""AgentNode — workflow node that delegates to the global AgentService.

Spec-bug fix (2026-06-04, Task 9): the plan's verbatim code called
``AgentService(self.db)`` and wrapped the (already-async) ``run`` in
``asyncio.to_thread``. The actual signatures in
``app/services/agent_service.py`` are::

    class AgentService:
        def __init__(self):                   # no-arg constructor (no eager vector_store)

        async def run(
            self,
            agent_id: int,
            message: str,
            tenant_id: int,
        ) -> str:                              # already async, opens its own DB session

so we instantiate ``AgentService()`` and ``await svc.run(...)`` directly.
The test reads from pool selector ``["input", "user_query"]`` (the plan's
verbatim ``["current"]`` was a 1-element selector that violates
``VariablePool.get``'s >= 2 contract — see test for the matching fix).

# Spec note: plan referenced "NodeExecError" but no such class exists in
# app/core/workflow/entities.py. Legacy executor uses ValueError, so we
# match that convention. Phase D may introduce a NodeExecError class.

# KB note (2026-06-06, Checkpoint 3): AgentService no longer eagerly
# constructs a vector_store. The per-KB embedder is resolved at chat
# time (each KB has its own embedding_model_config_id).

# M27 (2026-06-15): tenant_id fallback fix. Previously this node did
# ``tenant_id=d.tenant_id or 1`` which silently masked a config-missing
# bug as "always tenant 1". The correct priority is:
#   1. self.tenant_id  (workflow's tenant, injected by executor)
#   2. d.tenant_id     (node config override, rarely used)
#   3. raise ValueError (config is bad — surface it explicitly)
"""

import logging

from pydantic import Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.types import SegmentType
# Module-level import (not lazy) so tests can patch
# ``app.core.workflow.nodes.agent.AgentService`` with ``unittest.mock.patch``.
from lumen_services.agent_service import AgentService  # noqa: F401  (re-exported for patching)

logger = logging.getLogger(__name__)


class AgentNodeData(BaseNodeData):
    agent_id: int | None = None
    tenant_id: int | None = None


class AgentNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        cfg = {**config, "version": config.get("version", "1")}
        return AgentNodeData.model_validate(cfg)

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="response", type=SegmentType.STRING, description="Agent 回复"),
            OutputVar(name="usage", type=SegmentType.OBJECT, description="调用用量"),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, AgentNodeData)
        d = self._data
        if d.agent_id is None:
            raise ValueError("Agent 已失效")
        message = str(self.pool.get(["input", "user_query"]).value)
        # M27: tenant_id fallback priority is now explicit. Workflow's
        # injected ``self.tenant_id`` wins (the executor knows the
        # workflow row's tenant). Node-config ``d.tenant_id`` is a
        # legacy escape hatch but if both are missing we MUST raise
        # rather than silently default to tenant 1, which was a
        # cross-tenant data-bleed risk.
        if (
            d.tenant_id is not None
            and self.tenant_id is not None
            and d.tenant_id != self.tenant_id
        ):
            logger.warning(
                "AgentNode tenant_id=%s differs from workflow tenant_id=%s, "
                "using workflow's",
                d.tenant_id, self.tenant_id,
            )
        tenant_id = self.tenant_id if self.tenant_id is not None else d.tenant_id
        if tenant_id is None:
            raise ValueError(
                "AgentNode missing tenant_id — workflow config invalid"
            )
        # AgentService() is no-arg constructor; run() is already async and
        # opens its own DB session internally. Do NOT use asyncio.to_thread
        # or pass self.db.
        svc = AgentService()
        result = await svc.run(
            agent_id=d.agent_id,
            message=message,
            tenant_id=tenant_id,
        )
        return NodeRunResult(
            node_id=self.node_id,
            output_values={
                "response": str(result),
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            },
        )
