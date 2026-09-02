import pymysql
conn = pymysql.connect(host='localhost', port=3307, user='root', password='rootpassword', database='ai_platform', connect_timeout=5)
cur = conn.cursor()

cur.execute("SELECT id, title, user_id, created_at FROM conversations WHERE user_id = 1 ORDER BY id")
print("=== admin (uid=1) convs ===")
for r in cur.fetchall():
    title = r[1] if r[1] else '<NULL>'
    print(f"  id={r[0]:4d}  user={r[2]}  {title!r}  ({r[3]})")

cur.execute("SELECT COUNT(*) FROM conversations WHERE user_id IS NULL")
print(f"\nuser_id NULL: {cur.fetchone()[0]}")
print("sample NULL conv titles:")
cur.execute("SELECT id, title FROM conversations WHERE user_id IS NULL LIMIT 10")
for r in cur.fetchall():
    title = r[1] if r[1] else '<NULL>'
    print(f"  id={r[0]}  {title!r}")

cur.execute("SELECT id, username FROM users")
print("\n=== users ===")
for r in cur.fetchall():
    print(f"  id={r[0]:4d}  {r[1]}")

conn.close()