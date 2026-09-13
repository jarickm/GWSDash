import datetime
import sqlite3
import concurrent.futures
from old.app import fetch_google_data_for_date, bulk_save_metrics_to_sqlite, init_db, DB_NAME


def run_full_sync():
    print("Step 1: Initializing database tables...")
    init_db()

    print("Step 2: Clearing existing metrics to prepare for a clean overwrite...")
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('DELETE FROM daily_metrics')
        conn.commit()
        conn.close()
        print("Database cleared successfully.")
    except Exception as e:
        print(f"Error clearing database: {e}")
        return

    # Google Workspace Reports API retention limit is 180 days.
    # We fetch from 3 days ago back to 180 days ago to avoid Google's processing latency.
    today = datetime.date.today()
    days_to_fetch = [(today - datetime.timedelta(days=i)).isoformat() for i in range(3, 180)]

    print(f"\nStep 3: Preparing to download {len(days_to_fetch)} days of historical data.")
    print("Using 5 concurrent threads to prevent hitting Google Workspace API quota rate limits.\n")

    all_records = []
    completed_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_date = {executor.submit(fetch_google_data_for_date, date): date for date in days_to_fetch}

        for future in concurrent.futures.as_completed(future_to_date):
            date_str = future_to_date[future]
            completed_count += 1
            try:
                records = future.result()
                if records:
                    all_records.extend(records)
                    print(
                        f"[{completed_count}/{len(days_to_fetch)}] Synced {date_str} successfully - Found {len(records)} users.")
                else:
                    print(f"[{completed_count}/{len(days_to_fetch)}] Synced {date_str} - No active users found.")
            except Exception as e:
                print(f"[{completed_count}/{len(days_to_fetch)}] Error syncing {date_str}: {e}")

    print("\nStep 4: Writing retrieved records to SQLite...")
    if all_records:
        try:
            bulk_save_metrics_to_sqlite(all_records)
            print(f"Success! {len(all_records)} total daily records saved to '{DB_NAME}'.")
        except Exception as e:
            print(f"Error saving data to SQLite: {e}")
    else:
        print("No historical data was returned. Please verify your 'credentials-old.json' and permissions.")


if __name__ == "__main__":
    run_full_sync()