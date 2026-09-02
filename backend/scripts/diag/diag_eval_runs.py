import pymysql
conn = pymysql.connect(host='localhost', port=3307, user='root', password='rootpassword', database='ai_platform', connect_timeout=5)
cur = conn.cursor()

cur.execute('DESCRIBE eval_runs')
print('=== eval_runs ===')
for r in cur.fetchall():
    print(f'  {r[0]:30s}  {r[1]:30s}')

cur.execute('SELECT id, dataset_id, status, total_items, completed_items, created_by, created_at FROM eval_runs ORDER BY id DESC LIMIT 10')
print('\n=== latest 10 eval_runs ===')
for r in cur.fetchall():
    print(f'  id={r[0]:5d}  dataset={r[1]:4d}  status={r[2]:10s}  total={r[3]:3d}  done={r[4]:3d}  created_by={r[5]}  ({r[6]})')

cur.execute('SELECT COUNT(*) FROM eval_runs')
print(f'\ntotal eval_runs: {cur.fetchone()[0]}')

cur.execute('SELECT COUNT(*) FROM eval_datasets')
print(f'total eval_datasets: {cur.fetchone()[0]}')

cur.execute('SELECT id, name, created_by, kb_id FROM eval_datasets')
print('\n=== eval_datasets ===')
for r in cur.fetchall():
    print(f'  id={r[0]:4d}  kb={r[3]}  by={r[2]}  {r[1]!r}')

# Run 518 specific
cur.execute('SELECT * FROM eval_runs WHERE id = 518')
row = cur.fetchone()
if row:
    print(f'\n=== run 518 full row ===')
    cur.execute('DESCRIBE eval_runs')
    cols = [c[0] for c in cur.fetchall()]
    for c, v in zip(cols, row):
        print(f'  {c:30s} = {v!r}')

cur.execute('SELECT COUNT(*) FROM eval_run_results WHERE run_id = 518')
print(f'\nrun 518 results: {cur.fetchone()[0]}')

conn.close()