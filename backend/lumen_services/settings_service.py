from typing import Optional, Union
from sqlalchemy.orm import Session
from lumen_models.settings import SystemSettings, SecuritySettings
from lumen_schemas.settings import SystemSettingsUpdate, SecuritySettingsUpdate

class SettingsService:
    def get_system_settings(self, db: Session, tenant_id: int) -> Optional[SystemSettings]:
        return db.query(SystemSettings).filter(
            SystemSettings.tenant_id == tenant_id
        ).first()

    def update_system_settings(
        self,
        db: Session,
        tenant_id: int,
        data: Union[SystemSettingsUpdate, dict]
    ) -> SystemSettings:
        settings = self.get_system_settings(db, tenant_id)
        if not settings:
            settings = SystemSettings(tenant_id=tenant_id)
            db.add(settings)

        # Use explicit field assignment instead of arbitrary key assignment
        if isinstance(data, dict):
            update_data = data
        else:
            update_data = data.model_dump(exclude_unset=True)

        if "system_name" in update_data and update_data["system_name"] is not None:
            settings.system_name = update_data["system_name"]
        if "system_description" in update_data:
            settings.system_description = update_data["system_description"]
        if "default_model" in update_data:
            settings.default_model = update_data["default_model"]
        if "embedding_model" in update_data:
            settings.embedding_model = update_data["embedding_model"]
        if "chat_history_days" in update_data and update_data["chat_history_days"] is not None:
            settings.chat_history_days = update_data["chat_history_days"]

        db.commit()
        db.refresh(settings)
        return settings

    def get_security_settings(self, db: Session, tenant_id: int) -> Optional[SecuritySettings]:
        return db.query(SecuritySettings).filter(
            SecuritySettings.tenant_id == tenant_id
        ).first()

    def update_security_settings(
        self,
        db: Session,
        tenant_id: int,
        data: Union[SecuritySettingsUpdate, dict]
    ) -> SecuritySettings:
        settings = self.get_security_settings(db, tenant_id)
        if not settings:
            settings = SecuritySettings(tenant_id=tenant_id)
            db.add(settings)

        # Use explicit field assignment instead of arbitrary key assignment
        if isinstance(data, dict):
            update_data = data
        else:
            update_data = data.model_dump(exclude_unset=True)

        if "enforce_password_complexity" in update_data and update_data["enforce_password_complexity"] is not None:
            settings.enforce_password_complexity = update_data["enforce_password_complexity"]
        if "min_password_length" in update_data and update_data["min_password_length"] is not None:
            settings.min_password_length = update_data["min_password_length"]
        if "login_fail_lock_count" in update_data and update_data["login_fail_lock_count"] is not None:
            settings.login_fail_lock_count = update_data["login_fail_lock_count"]
        if "token_expire_minutes" in update_data and update_data["token_expire_minutes"] is not None:
            settings.token_expire_minutes = update_data["token_expire_minutes"]

        db.commit()
        db.refresh(settings)
        return settings