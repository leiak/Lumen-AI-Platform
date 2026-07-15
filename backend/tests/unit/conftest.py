# Break the celery_app <-> document_tasks circular import for unit
# tests that import document_tasks directly (e.g.
# test_document_tasks_notification.py, which targets the
# _emit_notification helper). celery_app.py imports
# document_tasks.process_document_task at module bottom; importing
# celery_app first lets it find the symbol once document_tasks
# finishes loading. Documented in MEMORY.md under "Frontend testing"
# and again in test_knowledge_user_id_in_task_params.py.
import lumen_tasks.celery_app  # noqa: F401,E402
