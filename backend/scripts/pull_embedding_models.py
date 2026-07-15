"""Pull a list of Ollama models in parallel via the HTTP API.

Streams progress for each model on its own line. Exits 0 only if all
pulls end with status=success.

Usage:
    python pull_embedding_models.py model1:tag [model2:tag ...]
"""
import sys
import threading
import time
import requests

OLLAMA = "http://localhost:11434"
TIMEOUT = 1800  # 30 min per model — large model on slow link can take a while


def pull(name: str) -> tuple[str, bool, str]:
    """Returns (name, success, last_status)."""
    sys.stdout.write(f"\n=== [{name}] starting ===\n")
    sys.stdout.flush()
    started = time.time()
    last_status = "unknown"
    try:
        r = requests.post(
            f"{OLLAMA}/api/pull",
            json={"name": name, "stream": True},
            stream=True,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            # `iter_lines(decode_unicode=True)` is unreliable across
            # requests versions — decode manually so we always work on str.
            if isinstance(line, (bytes, bytearray)):
                line = line.decode("utf-8", errors="replace")
            # line is NDJSON: {"status": "...", "digest": "...", "total": ..., "completed": ...}
            # We just prefix with [name] and forward.
            sys.stdout.write(f"[{name}] {line}\n")
            sys.stdout.flush()
            # Cheap status tracking — look for "status" key.
            if '"status"' in line:
                try:
                    import json as _json
                    obj = _json.loads(line)
                    last_status = obj.get("status", last_status)
                except Exception:
                    pass
            if last_status == "success":
                break
        elapsed = time.time() - started
        sys.stdout.write(f"=== [{name}] done in {elapsed:.1f}s (last_status={last_status}) ===\n")
        sys.stdout.flush()
        return (name, last_status == "success", last_status)
    except Exception as e:
        sys.stdout.write(f"=== [{name}] ERROR: {e} ===\n")
        sys.stdout.flush()
        return (name, False, str(e))


def main():
    if len(sys.argv) < 2:
        print("usage: pull_embedding_models.py model1[:tag] [model2[:tag] ...]", file=sys.stderr)
        sys.exit(2)
    models = sys.argv[1:]
    sys.stdout.write(f"Pulling {len(models)} model(s) in parallel from {OLLAMA}: {models}\n")
    sys.stdout.flush()

    threads = [threading.Thread(target=pull, args=(m,), daemon=True) for m in models]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Summary
    sys.stdout.write("\n=== Summary ===\n")
    sys.stdout.flush()
    # Re-run sequentially to grab success booleans — they're already in stdout,
    # but we want a structured pass/fail. Re-derive from a quick /api/show call.
    all_ok = True
    for m in models:
        try:
            r = requests.post(f"{OLLAMA}/api/show", json={"name": m}, timeout=10)
            ok = r.status_code == 200
        except Exception as e:
            ok = False
            print(f"  {m:40s}  verify FAILED: {e}")
        else:
            print(f"  {m:40s}  verified: {ok}")
        sys.stdout.flush()
        all_ok = all_ok and ok

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
