"""Tool-choice strategy registry for the agent run path.

Each agent can pick one of four strategies that decide which subset of its
configured tools is exposed to the LLM on a given turn:

    * AUTO          -> expose the full set of agent-configured tools and
                       let the LLM decide whether to call one
    * REQUIRED      -> expose the full set of tools and add a system hint
                       forcing the LLM to call one (LLM-side enforcement
                       varies by model)
    * NONE          -> expose no tools; the LLM can only answer in prose
    * SPECIFIC      -> expose only the tools whose names appear in
                       ``allowed`` (intersected with the agent's
                       configured tools, so we never advertise a tool the
                       agent doesn't actually own)

The "tool" objects passed in are dicts with at least a ``name`` key
(``{"name": "web_search", ...}``) — that matches the shape produced by
``AgentTool`` rows in the DB. The function returns the same shape so the
caller can pass the result straight to whatever LLM-bind layer it uses.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)


ToolDict = Dict[str, Any]


class ToolChoiceMode(str, Enum):
    """Per-agent tool choice strategy."""

    AUTO = "auto"
    REQUIRED = "required"
    NONE = "none"
    SPECIFIC = "specific"

    @classmethod
    def all(cls) -> List[str]:
        return [m.value for m in cls]

    @classmethod
    def coerce(cls, value: Optional[str]) -> "ToolChoiceMode":
        """Best-effort coercion from DB / JSON values."""
        if value is None or value == "":
            return cls.AUTO
        if isinstance(value, cls):
            return value
        s = str(value).strip().lower()
        for m in cls:
            if s == m.value or s == m.name.lower():
                return m
        logger.warning("Unknown tool_choice mode %r; defaulting to auto", value)
        return cls.AUTO


def _normalize_tools(tools: Iterable[Any]) -> List[ToolDict]:
    """Accept AgentTool rows, dicts, or strings and return a list of dicts."""
    out: List[ToolDict] = []
    for t in tools or []:
        if t is None:
            continue
        if isinstance(t, str):
            out.append({"name": t})
            continue
        if isinstance(t, dict):
            if "name" in t:
                out.append(dict(t))
            continue
        # SQLAlchemy model — best-effort
        name = getattr(t, "tool_name", None) or getattr(t, "name", None)
        if name:
            out.append(
                {
                    "name": name,
                    **{k: v for k, v in vars(t).items() if k not in ("name", "_sa_instance_state")},
                }
            )
    return out


def _normalize_allowed(allowed: Optional[Iterable[Any]]) -> List[str]:
    if not allowed:
        return []
    names: List[str] = []
    for a in allowed:
        if a is None:
            continue
        if isinstance(a, str):
            s = a.strip()
        else:
            s = str(a)
        if s:
            names.append(s)
    # de-dupe, preserve order
    seen = set()
    out: List[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def select_tools(
    available_tools: Optional[Iterable[Any]],
    mode: Optional[str],
    allowed: Optional[Iterable[Any]] = None,
    *,
    required_hint: Optional[bool] = None,
) -> List[ToolDict]:
    """Pick the tools to expose to the LLM for a single turn.

    Parameters
    ----------
    available_tools:
        The full set of tools configured on the agent (AgentTool rows,
        dicts, or strings).
    mode:
        One of the values in :class:`ToolChoiceMode` (str/enum/None).
    allowed:
        For ``SPECIFIC``: the names of tools the agent is allowed to use.
    required_hint:
        For ``REQUIRED``: if true, mark the returned tools with a
        ``tool_choice="required"`` hint flag (callers can decide whether
        to pass it through to the chat model). The default of None means
        "honour the agent's stored ``tool_choice_required``" — but since
        the caller already knows that flag, we accept it explicitly to
        keep this function pure.
    """
    tools = _normalize_tools(available_tools)
    m = ToolChoiceMode.coerce(mode)

    if m == ToolChoiceMode.NONE:
        return []

    if m == ToolChoiceMode.AUTO:
        return tools

    if m == ToolChoiceMode.REQUIRED:
        marked = []
        for t in tools:
            new = dict(t)
            if required_hint:
                new["tool_choice"] = "required"
            marked.append(new)
        return marked

    if m == ToolChoiceMode.SPECIFIC:
        wanted = set(_normalize_allowed(allowed))
        if not wanted:
            return []
        return [t for t in tools if t.get("name") in wanted]

    # Defensive fallback
    return tools


def tool_choice_hint(
    mode: Optional[str],
    required: Optional[bool] = None,
) -> Optional[str]:
    """Return a string the caller can pass as the chat model's ``tool_choice``.

    Returns ``"required"`` when the agent wants the LLM to always call a
    tool and the model supports it, ``"none"`` when no tools should be
    used, and ``None`` (let the model decide) otherwise. This is a small
    helper so the run path doesn't have to special-case the modes
    itself.
    """
    m = ToolChoiceMode.coerce(mode)
    if m == ToolChoiceMode.NONE:
        return "none"
    if m == ToolChoiceMode.REQUIRED and required:
        return "required"
    return None
