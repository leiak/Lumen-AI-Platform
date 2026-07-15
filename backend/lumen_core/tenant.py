from contextvars import ContextVar
from typing import Optional

tenant_id: ContextVar[Optional[int]] = ContextVar("tenant_id", default=None)


class TenantContext:
    @staticmethod
    def get_tenant_id() -> Optional[int]:
        return tenant_id.get()

    @staticmethod
    def set_tenant_id(tid: int):
        tenant_id.set(tid)

    @staticmethod
    def clear():
        tenant_id.set(None)
