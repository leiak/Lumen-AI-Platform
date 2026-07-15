"""
Multi-Agent Team models.

A team is a coordinated group of agents managed by a single "manager" agent.
Workers are stored in AgentTeamMember, optional explicit routing rules in
AgentTeamRoute. The manager decides (by default) which workers to invoke for
a given user message, and the system aggregates their outputs into a final
answer.
"""
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    ForeignKey,
    JSON,
    Boolean,
    Index,
)
from sqlalchemy.orm import relationship
from lumen_models.base import BaseModel


class AgentTeam(BaseModel):
    __tablename__ = "agent_teams"

    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    # FK to the Agent that acts as the manager / router / aggregator
    manager_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    # Routing policy: "manager_decides" | "round_robin" | "first_match"
    route_policy = Column(String(32), nullable=False, default="manager_decides")
    # Optional fixed aggregator prompt (used when no manager is in play, or
    # to override the manager's system prompt for the final synthesis step).
    aggregator_prompt = Column(Text, nullable=True)
    # Free-form config blob (e.g. max_iterations, parallel/sequential)
    config = Column(JSON, nullable=True)

    manager = relationship("Agent", foreign_keys=[manager_agent_id])
    tenant = relationship("Tenant", backref="agent_teams")
    members = relationship(
        "AgentTeamMember",
        back_populates="team",
        cascade="all, delete-orphan",
    )
    routes = relationship(
        "AgentTeamRoute",
        back_populates="team",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_agentteam_tenant_active", "tenant_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<AgentTeam(id={self.id}, name={self.name}, manager_agent_id={self.manager_agent_id})>"


class AgentTeamMember(BaseModel):
    __tablename__ = "agent_team_members"

    team_id = Column(Integer, ForeignKey("agent_teams.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    # Human-readable role for this worker (e.g. "researcher", "writer")
    role = Column(String(64), nullable=False, default="worker")
    # Lower number = higher priority. Used for round_robin ordering and
    # tie-breaking when the manager picks among several candidates.
    priority = Column(Integer, nullable=False, default=100)
    is_active = Column(Boolean, default=True, nullable=False)
    # Optional JSON config for this member (e.g. weight, parallelism, scope)
    config = Column(JSON, nullable=True)

    team = relationship("AgentTeam", back_populates="members")
    agent = relationship("Agent", foreign_keys=[agent_id])

    __table_args__ = (
        Index("idx_member_team_agent", "team_id", "agent_id"),
    )

    def __repr__(self) -> str:
        return f"<AgentTeamMember(team_id={self.team_id}, agent_id={self.agent_id}, role={self.role!r})>"


class AgentTeamRoute(BaseModel):
    """Optional explicit routing rules for the `first_match` policy.

    A rule maps a keyword / pattern to a target agent_id. When the policy is
    `first_match`, the team scans the user message for any of `keywords`
    and routes to the first matching rule (by priority then id).
    """
    __tablename__ = "agent_team_routes"

    team_id = Column(Integer, ForeignKey("agent_teams.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    keywords = Column(JSON, nullable=False, default=list)  # list[str]
    priority = Column(Integer, nullable=False, default=100)

    team = relationship("AgentTeam", back_populates="routes")
    agent = relationship("Agent", foreign_keys=[agent_id])
