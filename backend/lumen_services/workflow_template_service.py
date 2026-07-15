from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from lumen_models.workflow_template import WorkflowTemplate
from lumen_models.workflow import Workflow
from lumen_models.user import User
from lumen_schemas.workflow_template import WorkflowTemplateCreate


class WorkflowTemplateService:
    def list_templates(
        self,
        db: Session,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[WorkflowTemplate]:
        query = db.query(WorkflowTemplate)
        if category:
            query = query.filter(WorkflowTemplate.category == category)
        if search:
            like = f"%{search}%"
            query = query.filter(WorkflowTemplate.name.like(like))
        # tag filter is JSON-contains; we fetch and filter in python to avoid
        # dialect-specific JSON predicates.
        templates = query.order_by(WorkflowTemplate.created_at.desc()).all()
        if tag:
            templates = [
                t for t in templates
                if t.tags and tag in (t.tags if isinstance(t.tags, list) else [])
            ]
        return templates

    def get_template(self, db: Session, template_id: int) -> Optional[WorkflowTemplate]:
        return db.query(WorkflowTemplate).filter(WorkflowTemplate.id == template_id).first()

    def create_template(
        self,
        db: Session,
        current_user: User,
        data: WorkflowTemplateCreate,
    ) -> WorkflowTemplate:
        # Resolve workflow_json: prefer explicit blob, otherwise load from
        # the current user's workflow.
        workflow_json: Optional[Dict[str, Any]] = data.workflow_json
        if workflow_json is None and data.workflow_id is not None:
            wf = db.query(Workflow).filter(
                Workflow.id == data.workflow_id,
                Workflow.tenant_id == current_user.tenant_id,
            ).first()
            if not wf:
                raise ValueError("Source workflow not found or not owned by current tenant")
            workflow_json = wf.definition

        if workflow_json is None:
            raise ValueError("workflow_json is required (either pass workflow_id or workflow_json)")

        template = WorkflowTemplate(
            name=data.name,
            description=data.description,
            category=data.category or "general",
            tags=data.tags or [],
            workflow_json=workflow_json,
            author_id=current_user.id,
            author_name=current_user.full_name or current_user.username,
            tenant_id=current_user.tenant_id,
            downloads=0,
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        return template

    @staticmethod
    def _normalize_definition(definition: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Walk a workflow definition and copy legacy ``data`` payloads into
        ``config`` for any node that doesn't have a ``config`` yet.

        Templates published with the old "everything lives in ``data``"
        shape will still import into a workflow the executor understands.
        """
        if not isinstance(definition, dict):
            return definition
        nodes = definition.get("nodes")
        if not isinstance(nodes, list):
            return definition
        for node in nodes:
            if not isinstance(node, dict):
                continue
            cfg = node.get("config")
            data = node.get("data")
            if (not isinstance(cfg, dict) or not cfg) and isinstance(data, dict):
                node["config"] = data
        return definition

    def import_template(
        self,
        db: Session,
        template_id: int,
        current_user: User,
    ) -> Workflow:
        template = self.get_template(db, template_id)
        if not template:
            raise ValueError("Template not found")

        # Deep-ish copy of the JSON blob so future template edits
        # don't mutate the user's workflow.
        wf_json = template.workflow_json
        if isinstance(wf_json, dict):
            import copy
            wf_json = copy.deepcopy(wf_json)

        # Normalize: any node that only has ``data`` (legacy shape) gets
        # its payload copied into ``config`` so the unified executor
        # picks it up.
        wf_json = self._normalize_definition(wf_json)

        new_name = f"{template.name} (from template)"
        new_workflow = Workflow(
            name=new_name,
            description=template.description,
            definition=wf_json,
            tenant_id=current_user.tenant_id,
            is_active=True,
        )
        db.add(new_workflow)

        # Bump download counter
        template.downloads = (template.downloads or 0) + 1

        db.commit()
        db.refresh(new_workflow)
        return new_workflow
