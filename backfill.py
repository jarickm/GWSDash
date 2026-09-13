import datetime
import time
from old.app import sync_google_data, init_db

print("=== Starting OneWorkspace Historical Backfill ===")
init_db()

# Range: August 1, 2026 to T-3 days ago (September 3, 2026)
start_date = datetime.date(2026, 8, 1)
end_date = datetime.date.today() - datetime.timedelta(days=3)

current_date = start_date
synced_count = 0

while current_date <= end_date:
    date_str = current_date.isoformat()
    print(f"[{synced_count + 1}] Caching Workspace data for: {date_str}...")
    try:
        sync_google_data(date_str)
        synced_count += 1
        # Gentle 0.5s delay to stay well within Google API rate limits
        time.sleep(0.5)
    except Exception as e:
        print(f"  --> Warning on {date_str}: {e}")

    current_date += datetime.timedelta(days=1)

print(f"\n Success! Backfilled {synced_count} historical dates into SQLite ('adoption_cache.db').")