from sqlalchemy import text

from lumen_core.database import engine


_NOTIFICATIONS_DDL = """
CREATE TABLE IF NOT EXISTS notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    type VARCHAR(32) NOT NULL,
    title VARCHAR(200) NOT NULL,
    body TEXT NULL,
    resource_type VARCHAR(32) NULL,
    resource_id INT NULL,
    metadata_json JSON NULL,
    read_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    INDEX ix_notifications_user_id (user_id),
    INDEX ix_notifications_user_unread_created (user_id, read_at, created_at),
    CONSTRAINT fk_notifications_user_id FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def ensure_notifications_table() -> None:
    """Create the notifications table if it doesn't exist. Idempotent.
    Mirrors the _column_exists pattern used elsewhere in
    app.core.database for migrations without Alembic.
    """
    with engine.begin() as conn:
        conn.execute(text(_NOTIFICATIONS_DDL))
