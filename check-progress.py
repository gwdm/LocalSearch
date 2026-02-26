import sqlite3

conn = sqlite3.connect('data/localsearch_meta.db')
c = conn.cursor()

c.execute('SELECT status, COUNT(*) FROM files GROUP BY status')
results = c.fetchall()

print("\nCurrent status:")
print("-" * 40)
for status, count in results:
    print(f"{status:10s}: {count:,}")

total = sum([count for _, count in results])
print("-" * 40)
print(f"{'Total':10s}: {total:,}")

conn.close()
