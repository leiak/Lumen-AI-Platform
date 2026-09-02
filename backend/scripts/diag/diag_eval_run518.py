"""复现 GET /api/v1/eval/runs/518 端点流程,抓 traceback。"""
import os
import sys
import traceback
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from lumen_core.config import settings
from lumen_core.database import SessionLocal
from lumen_models.eval_run import EvalRun
from lumen_models.eval_dataset import EvalDataset
from lumen_services.eval_run_service import EvalRunService
from lumen_api.v1.eval_runs import _to_read, _to_result_read

db = SessionLocal()
try:
    print("=== service.get_run(db, run_id=518, tenant_id=1) ===")
    svc = EvalRunService()
    run = svc.get_run(db, run_id=518, tenant_id=1)
    print(f"  type={type(run).__name__}, id={run.id if run else None}")

    print("\n=== service.list_results(...) ===")
    results, total = svc.list_results(db, run_id=518, tenant_id=1, page=1, page_size=100)
    print(f"  results={len(results)}, total={total}")

    print("\n=== _to_read(run) ===")
    read = _to_read(run)
    print(f"  type={type(read).__name__}")
    print(f"  id={read.id}")
    print(f"  config={read.config}")

    print("\n=== _to_result_read(results[0]) ===")
    result_read = _to_result_read(results[0])
    print(f"  id={result_read.id}")
    print(f"  retrieval_metrics={result_read.retrieval_metrics}")
    print(f"  answer_metrics={result_read.answer_metrics}")
except Exception:
    traceback.print_exc()
finally:
    db.close()