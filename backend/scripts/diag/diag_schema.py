import pymysql
conn = pymysql.connect(host='localhost', port=3307, user='root', password='rootpassword', database='ai_platform', connect_timeout=5)
cur = conn.cursor()
cur.execute('DESCRIBE workflow_node_runs')
print('=== workflow_node_runs ===')
for r in cur.fetchall():
    print(f'  {r[0]:30s}  {r[1]:30s}')
cur.execute('DESCRIBE workflow_runs')
print('\n=== workflow_runs ===')
for r in cur.fetchall():
    print(f'  {r[0]:30s}  {r[1]:30s}')
cur.execute('DESCRIBE workspaces')
print('\n=== workspaces ===')
for r in cur.fetchall():
    print(f'  {r[0]:30s}  {r[1]:30s}')
cur.execute('DESCRIBE knowledge_bases')
print('\n=== knowledge_bases ===')
for r in cur.fetchall():
    print(f'  {r[0]:30s}  {r[1]:30s}')
cur.execute('DESCRIBE workspace_member_permissions')
print('\n=== workspace_member_permissions ===')
for r in cur.fetchall():
    print(f'  {r[0]:30s}  {r[1]:30s}')
cur.execute("SHOW TABLES LIKE 'workspace%'")
print('\nworkspace tables:')
for r in cur.fetchall():
    print(f'  {r[0]}')
conn.close()