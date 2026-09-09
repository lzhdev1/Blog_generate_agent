import sqlite3

conn = sqlite3.connect('blog_agent.db')
cursor = conn.cursor()

# 1. 查看所有表
print('=== 数据库中的所有表 ===')
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
for t in tables:
    print(f'  - {t[0]}')

# 2. 查看 blog_task 表结构
print()
print('=== blog_task 表结构 ===')
cursor.execute('PRAGMA table_info(blog_task)')
columns = cursor.fetchall()
for col in columns:
    pk = '是' if col[5] else '否'
    nn = '是' if col[3] else '否'
    print(f'  {col[1]:20s} {col[2]:15s} 主键:{pk}  非空:{nn}')

# 3. 查看表中的数据
print()
print('=== blog_task 表中的数据 ===')
cursor.execute('SELECT id, topic, status, selected_title, outline_confirmed FROM blog_task')
rows = cursor.fetchall()
print(f'共 {len(rows)} 条记录:')
for row in rows:
    topic = row[1][:25] + '...' if len(row[1]) > 25 else row[1]
    print(f'  id={row[0]}, topic={topic}, status={row[2]}, selected_title={row[3]}, outline_confirmed={row[4]}')

conn.close()
