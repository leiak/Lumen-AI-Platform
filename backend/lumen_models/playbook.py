"""M35: Playbook persistence model.

A Playbook is a tenant-scoped (or built-in) bundle of style tokens
(palette / typography / keywords / avoid) that gets injected into
image-gen prompts and TTS voice direction. The YAML source is kept
verbatim in ``yaml_content``; the parsed style tokens live in
``style_tokens`` (JSON) for fast filtering (e.g. ``scope=image``).

``is_builtin=True`` rows are seeded by ``seed_m35_default_models.py`` and
are not editable / deletable by tenants — the API guards these.

Spec: docs-internal/superpowers/specs/M35-playbook-schema.md
"""
from sqlalchemy import Column, Integer, String, Text, JSON, ForeignKey, Index, Boolean
from lumen_models.base import BaseModel


class Playbook(BaseModel):
    __tablename__ = "playbooks"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    yaml_content = Column(Text, nullable=False)
    # Parsed style tokens (dict). Populated by PlaybookService on create/update.
    style_tokens = Column(JSON, nullable=True)
    # Scope: list[str] of applicable targets, e.g. ["image", "tts", "video"].
    # Used by the API filter ``?scope=image`` and the inject helper's
    # ``validate_scope`` check.
    scope = Column(JSON, nullable=True)
    # Built-in playbooks are seeded by lumen_scripts.seed_m35_default_models.
    # API endpoints refuse to update or delete these.
    is_builtin = Column(Boolean, nullable=False, default=False)
    # Nullable: built-ins don't have a creator.
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        # A tenant can have many playbooks but only one with a given name
        # (allows simple lookup). Built-ins all share tenant_id=1.
        Index(
            "uq_playbook_tenant_name",
            "tenant_id", "name",
            unique=True,
        ),
    )
