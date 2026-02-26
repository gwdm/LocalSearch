"""Monitor ingestion progress in real-time."""
import sqlite3
import time
from datetime import datetime

conn = sqlite3.connect('data/localsearch_meta.db')

print("LocalSearch Ingestion Monitor")
print("=" * 60)
print("Press Ctrl+C to stop monitoring\n")

last_pending = None
last_indexed = None
last_time = time.time()

try:
    while True:
        c = conn.cursor()
        c.execute('SELECT status, COUNT(*) FROM files GROUP BY status')
        status_dict = {status: count for status, count in c.fetchall()}
        
        pending = status_dict.get('pending', 0)
        indexed = status_dict.get('indexed', 0)
        errors = status_dict.get('error', 0)
        
        now = datetime.now().strftime('%H:%M:%S')
        
        # Calculate rates
        if last_pending is not None:
            elapsed = time.time() - last_time
            processed = last_pending - pending
            indexed_new = indexed - last_indexed
            rate = processed / elapsed if elapsed > 0 else 0
            
            eta_seconds = (pending / rate) if rate > 0 else 0
            eta_hours = eta_seconds / 3600
            
            print(f"[{now}] Pending: {pending:,} | Indexed: {indexed:,} (+{indexed_new}) | "
                  f"Errors: {errors:,} | Rate: {rate*60:.1f} files/min | ETA: {eta_hours:.1f}h")
        else:
            print(f"[{now}] Pending: {pending:,} | Indexed: {indexed:,} | Errors: {errors:,}")
        
        last_pending = pending
        last_indexed = indexed
        last_time = time.time()
        
        time.sleep(30)  # Update every 30 seconds
        
except KeyboardInterrupt:
    print("\n\nMonitoring stopped.")
finally:
    conn.close()
