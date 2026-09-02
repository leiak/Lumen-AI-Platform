import pymysql
conn = pymysql.connect(host='localhost', port=3307, user='root', password='rootpassword', database='ai_platform', connect_timeout=5, charset='utf8mb4')
cur = conn.cursor()

# Conversations by user (handle NULL minid)
cur.execute('''SELECT COALESCE(user_id, -1) AS uid, COUNT(*) AS cnt,
               MIN(id) AS minid, MAX(id) AS maxid
               FROM conversations GROUP BY uid ORDER BY cnt DESC''')
print('=== conversations by user ===')
for r in cur.fetchall():
    print(f'  user={r[0]:4d}  cnt={r[1]:4d}  id_range={r[2] or "-"}..{r[3] or "-"}')

cur.execute("SELECT title, COUNT(*) FROM conversations WHERE title IS NOT NULL GROUP BY title ORDER BY COUNT(*) DESC LIMIT 15")
print('\n=== top 15 conv titles ===')
for title, cnt in cur.fetchall():
    print(f'  {cnt:3d}x  {title!r}')

# Sample messages containing 'hello'
cur.execute("SELECT id, conversation_id, role, LEFT(content, 60) AS preview FROM messages WHERE content LIKE '%hello%' ORDER BY id DESC LIMIT 10")
print('\n=== recent hello messages ===')
for r in cur.fetchall():
    print(f'  id={r[0]:5d}  conv={r[1]:4d}  {r[2]:5s}  {r[3]!r}')

# Sample conv with team_id
cur.execute("SELECT COUNT(*) FROM conversations WHERE team_id IS NOT NULL")
print(f'\nconversations with team_id: {cur.fetchone()[0]}')

# team_id top by frequency
cur.execute("SELECT team_id, COUNT(*) FROM conversations WHERE team_id IS NOT NULL GROUP BY team_id ORDER BY COUNT(*) DESC LIMIT 10")
print('top 10 team_id by conv count:')
for r in cur.fetchall():
    print(f'  team_id={r[0]:4d}  convs={r[1]}')

# users with admin/regular prefix likely fixture
cur.execute("SELECT COUNT(*) FROM users WHERE username LIKE '%test%' OR username LIKE 'other%'")
print(f'\nfixture users (test/other): {cur.fetchone()[0]}')

# Total counts
cur.execute("SELECT COUNT(*) FROM conversations")
print(f'total conversations: {cur.fetchone()[0]}')
cur.execute("SELECT COUNT(*) FROM messages")
print(f'total messages: {cur.fetchone()[0]}')
cur.execute("SELECT COUNT(*) FROM users")
print(f'total users: {cur.fetchone()[0]}')
cur.execute("SELECT COUNT(*) FROM agent_teams")
print(f'total agent_teams: {cur.fetchone()[0]}')
cur.execute("SELECT COUNT(*) FROM agent_team_members")
print(f'total agent_team_members: {cur.fetchone()[0]}')

conn.close()