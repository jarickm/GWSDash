import os
import sys
import datetime
import time
import re
import csv
import concurrent.futures
from collections import defaultdict
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.environ.get('SERVICE_ACCOUNT_FILE', os.path.join(BASE_DIR, 'old/credentials-old.json'))

SUPABASE_DB_URL = os.environ.get('DATABASE_URL')
if not SUPABASE_DB_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set in your .env file.")

db_engine = create_engine(
    SUPABASE_DB_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
    pool_pre_ping=True
)

ALLOWED_DOMAIN = os.environ.get('ALLOWED_DOMAIN', 'coolaireconsolidated.com')
ADMIN_EMAIL = os.environ.get('WORKSPACE_ADMIN_EMAIL', 'jarick.montojo@coolaireconsolidated.com')

# Quota and contract license defaults
ORGANIZATION_STORAGE_QUOTA_GB = float(os.environ.get('STORAGE_QUOTA_GB', '780000.0'))
TOTAL_CONTRACT_LICENSES = int(os.environ.get('TOTAL_LICENSES', '156'))

# Kollab Contract Details in PHP
KOLLAB_SEAT_ANNUAL_USD = float(os.environ.get('KOLLAB_SEAT_ANNUAL_USD', '264.00'))
USD_TO_PHP_RATE = float(os.environ.get('USD_TO_PHP_RATE', '58.00'))

KOLLAB_ANNUAL_COST_PHP = KOLLAB_SEAT_ANNUAL_USD * USD_TO_PHP_RATE  # ₱15,312.00
KOLLAB_MONTHLY_COST_PHP = KOLLAB_ANNUAL_COST_PHP / 12.0  # ₱1,276.00
KOLLAB_DAILY_COST_PHP = KOLLAB_ANNUAL_COST_PHP / 365.0  # ₱41.95

KOLLAB_RENEWAL_DATE_STR = os.environ.get('KOLLAB_CONTRACT_RENEWAL_DATE', '2027-04-30')

SCOPES = [
    'https://www.googleapis.com/auth/admin.directory.user.readonly',
    'https://www.googleapis.com/auth/admin.directory.group.readonly',
    'https://www.googleapis.com/auth/admin.reports.usage.readonly',
    'https://www.googleapis.com/auth/admin.reports.audit.readonly',
    'https://www.googleapis.com/auth/apps.licensing',
    'https://www.googleapis.com/auth/drive'
]

DEPARTMENT_TAXONOMY = {
    'Finance': {
        'batch': 'Batch 1', 'focus': 'Business Operations',
        'aliases': ['finance', 'fa', 'billing', 'disbursement', 'ap', 'ar', 'financial']
    },
    'Accounting': {
        'batch': 'Batch 1', 'focus': 'Business Operations',
        'aliases': ['accounting', 'acct', 'bookkeeper', 'audit_acct', 'general_accounting', 'ledger']
    },
    'CNC & Treasury': {
        'batch': 'Batch 1', 'focus': 'Business Operations',
        'aliases': ['cnc', 'treasury', 'cash', 'treasurer']
    },
    'Credit and Collection': {
        'batch': 'Batch 1', 'focus': 'Business Operations',
        'aliases': ['credit and collection', 'credit & collection', 'collection', 'credit', 'collections', 'collector']
    },
    'Purchasing': {
        'batch': 'Batch 1', 'focus': 'Business Operations',
        'aliases': ['purchasing', 'procurement', 'purch', 'buyer', 'sourcing']
    },
    'Sales': {
        'batch': 'Batch 1', 'focus': 'Business Operations',
        'aliases': ['sales', 'commercial', 'account executive', 'business development', 'bdr']
    },
    'Service': {
        'batch': 'Batch 1', 'focus': 'Business Operations',
        'aliases': ['service', 'technical_service', 'technician', 'maintenance', 'hvac', 'aftersales']
    },
    'Production': {
        'batch': 'Batch 2', 'focus': 'Operations & Compliance',
        'aliases': ['production', 'manufacturing', 'plant', 'factory', 'assembly', 'fabrication']
    },
    'Warehouse': {
        'batch': 'Batch 2', 'focus': 'Operations & Compliance',
        'aliases': ['warehouse', 'logistics', 'inventory', 'stock', 'receiving', 'storekeeper', 'warehousing']
    },
    'HR': {
        'batch': 'Batch 2', 'focus': 'Operations & Compliance',
        'aliases': ['hr', 'human resources', 'human_resources', 'people', 'personnel', 'admin_hr']
    },
    'Audit': {
        'batch': 'Batch 2', 'focus': 'Operations & Compliance',
        'aliases': ['audit', 'internal_audit', 'compliance', 'qa_audit']
    },
    'Asset': {
        'batch': 'Batch 3', 'focus': 'Specialized Operations',
        'aliases': ['asset', 'facilities', 'fleet', 'machinery', 'property']
    },
    'Marketing': {
        'batch': 'Batch 3', 'focus': 'Specialized Operations',
        'aliases': ['marketing', 'mktg', 'creatives', 'branding', 'graphics', 'digital', 'digital_marketing', 'media']
    },
    'Imports': {
        'batch': 'Batch 3', 'focus': 'Specialized Operations',
        'aliases': ['imports', 'customs', 'shipping', 'brokerage', 'importation', 'forwarding']
    },
    'IT Department': {
        'batch': 'IT', 'focus': 'Advanced Workspace Administration',
        'aliases': ['it', 'tech', 'sysadmin', 'information technology', 'systems', 'edp', 'developer']
    },
    'Management': {
        'batch': 'Executive', 'focus': 'Executive Governance',
        'aliases': ['management', 'executive', 'c-level', 'board', 'director', 'president', 'ceo', 'coo',
                    'general management']
    }
}

LAG_BUFFER_DAYS = 3


def get_delegated_credentials(subject_email=None):
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(f"Missing Service Account key: {SERVICE_ACCOUNT_FILE}")
    target_email = subject_email or ADMIN_EMAIL
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return creds.with_subject(target_email)


def extract_param_val(params_dict, name):
    """Safely extracts integer values from Google usage report parameters."""
    obj = params_dict.get(name, {})
    for k in ['intValue', 'stringValue', 'value']:
        if k in obj and obj[k] is not None:
            try:
                return int(obj[k])
            except (ValueError, TypeError):
                pass
    return 0


def get_domain_inception_date(dir_service):
    """
    Finds the absolute earliest creation date of any user account in the domain.
    This marks the exact day your Google Workspace instance was created.
    """
    print("[*] Detecting the absolute start date of your Google Workspace domain...")
    earliest_date = datetime.date.today()

    try:
        page_token = None
        while True:
            res = dir_service.users().list(
                customer='my_customer',
                fields="nextPageToken, users(creationTime)",
                maxResults=500,
                pageToken=page_token
            ).execute(num_retries=3)

            for u in res.get('users', []):
                c_time = u.get('creationTime')
                if c_time:
                    u_date = datetime.date.fromisoformat(c_time[:10])
                    if u_date < earliest_date:
                        earliest_date = u_date

            page_token = res.get('nextPageToken')
            if not page_token:
                break

        print(f"    [✓] Domain launch date detected: {earliest_date.isoformat()}")
        return earliest_date

    except Exception as e:
        fallback = datetime.date.today() - datetime.timedelta(days=1825)
        print(f"    [!] Could not read launch date ({e}), defaulting to: {fallback.isoformat()}")
        return fallback


def init_database_tables():
    """Auto-creates and migrates all Supabase PostgreSQL tables."""
    print("[*] Verifying & auto-creating database schema in Supabase...")
    with db_engine.begin() as conn:
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS user_departments (
                email VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255),
                department VARCHAR(255),
                batch VARCHAR(100),
                is_enrolled_in_2sv BOOLEAN DEFAULT FALSE,
                is_suspended BOOLEAN DEFAULT FALSE,
                last_login_time VARCHAR(100),
                drive_bytes BIGINT DEFAULT 0,
                gmail_bytes BIGINT DEFAULT 0,
                total_storage_bytes BIGINT DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS daily_metrics (
                date VARCHAR(20) NOT NULL,
                email VARCHAR(255) NOT NULL,
                name VARCHAR(255),
                department VARCHAR(255),
                batch VARCHAR(100),
                docs INT DEFAULT 0,
                sheets INT DEFAULT 0,
                forms INT DEFAULT 0,
                slides INT DEFAULT 0,
                calendar_events INT DEFAULT 0,
                meet_calls INT DEFAULT 0,
                meet_minutes INT DEFAULT 0,
                meet_created_calls INT DEFAULT 0,
                meet_created_minutes INT DEFAULT 0,
                meet_joined_calls INT DEFAULT 0,
                meet_joined_minutes INT DEFAULT 0,
                emails INT DEFAULT 0,
                drive_bytes BIGINT DEFAULT 0,
                gmail_bytes BIGINT DEFAULT 0,
                estimated_minutes INT DEFAULT 0,
                PRIMARY KEY (date, email)
            );
            CREATE TABLE IF NOT EXISTS department_checklists (
                department VARCHAR(255) NOT NULL,
                item_id VARCHAR(255) NOT NULL,
                completed INT DEFAULT 0,
                updated_at VARCHAR(100),
                PRIMARY KEY (department, item_id)
            );
            CREATE TABLE IF NOT EXISTS department_framework (
                department VARCHAR(255) PRIMARY KEY,
                batch VARCHAR(100) NOT NULL,
                focus VARCHAR(255) NOT NULL,
                lead_name VARCHAR(255) NOT NULL,
                target_pts VARCHAR(100) NOT NULL,
                workflow TEXT NOT NULL,
                shared_drive VARCHAR(255) NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS organization_governance_pool (
                id INT PRIMARY KEY DEFAULT 1,
                total_contract_licenses INT NOT NULL DEFAULT 156,
                assigned_licenses INT DEFAULT 0,
                total_workspace_users INT NOT NULL DEFAULT 0,
                available_accounts INT NOT NULL DEFAULT 0,
                active_collaborators INT DEFAULT 0,
                dormant_accounts INT DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS department_governance (
                department VARCHAR(255) PRIMARY KEY,
                batch VARCHAR(100),
                total_assigned_seats INT DEFAULT 0,
                active_seats INT DEFAULT 0,
                dormant_seats INT DEFAULT 0,
                suspended_seats INT DEFAULT 0,
                two_factor_enforced_seats INT DEFAULT 0,
                admin_users_count INT DEFAULT 0,
                admin_resets INT DEFAULT 0,
                self_resets INT DEFAULT 0,
                total_password_resets INT DEFAULT 0,
                two_factor_coverage_pct NUMERIC(5, 2) DEFAULT 0.0,
                total_storage_bytes BIGINT DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS shared_spaces (
                space_id VARCHAR(100) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                department VARCHAR(255),
                space_type VARCHAR(50) DEFAULT 'Shared Drive',
                owner_lead VARCHAR(255),
                storage_bytes BIGINT DEFAULT 0,
                member_count INT DEFAULT 0,
                description TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS space_members (
                id SERIAL PRIMARY KEY,
                space_id VARCHAR(100) NOT NULL,
                name VARCHAR(255),
                email VARCHAR(255),
                role VARCHAR(100) DEFAULT 'Member',
                department VARCHAR(255),
                UNIQUE (space_id, email)
            );
            CREATE TABLE IF NOT EXISTS org_storage_snapshots (
                snapshot_date VARCHAR(20) PRIMARY KEY,
                total_quota_gb NUMERIC(12, 2),
                used_storage_gb NUMERIC(12, 2),
                personal_drives_gb NUMERIC(12, 2),
                gmail_gb NUMERIC(12, 2),
                shared_drives_gb NUMERIC(12, 2),
                unattributed_system_gb NUMERIC(12, 2) DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS meet_recordings (
                recording_id VARCHAR(255) PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                organizer_email VARCHAR(255),
                organizer_name VARCHAR(255),
                department VARCHAR(255),
                batch VARCHAR(100),
                size_bytes BIGINT DEFAULT 0,
                duration_minutes INT DEFAULT 0,
                created_at TIMESTAMP,
                web_view_link TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS cross_dept_collaboration (
                id SERIAL PRIMARY KEY,
                source_department VARCHAR(255) NOT NULL,
                target_department VARCHAR(255) NOT NULL,
                interaction_type VARCHAR(100) DEFAULT 'file_share',
                interaction_count INT DEFAULT 1,
                audit_date VARCHAR(20) NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (source_department, target_department, audit_date, interaction_type)
            );
            CREATE TABLE IF NOT EXISTS user_collaboration_events (
                id SERIAL PRIMARY KEY,
                actor_email VARCHAR(255) NOT NULL,
                actor_name VARCHAR(255),
                source_department VARCHAR(255) NOT NULL,
                target_email VARCHAR(255) NOT NULL,
                target_department VARCHAR(255) NOT NULL,
                interaction_type VARCHAR(100) DEFAULT 'file_share',
                interaction_count INT DEFAULT 1,
                audit_date VARCHAR(20) NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (actor_email, target_email, audit_date, interaction_type)
            );

            CREATE TABLE IF NOT EXISTS password_reset_events (
                id SERIAL PRIMARY KEY,
                timestamp VARCHAR(50) NOT NULL,
                target_email VARCHAR(255) NOT NULL,
                target_name VARCHAR(255),
                department VARCHAR(255),
                reset_type VARCHAR(100) NOT NULL,
                initiator VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (timestamp, target_email, reset_type)
            );

            CREATE TABLE IF NOT EXISTS dlp_file_exposures (
                id SERIAL PRIMARY KEY,
                timestamp VARCHAR(50) NOT NULL,
                owner_name VARCHAR(255),
                owner_email VARCHAR(255) NOT NULL,
                department VARCHAR(255),
                doc_title TEXT NOT NULL,
                doc_type VARCHAR(100),
                recipient VARCHAR(255),
                recipient_domain VARCHAR(255),
                visibility VARCHAR(100),
                is_public_link BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (timestamp, owner_email, doc_title, recipient)
            );

            CREATE TABLE IF NOT EXISTS oauth_app_authorizations (
                id SERIAL PRIMARY KEY,
                timestamp VARCHAR(50) NOT NULL,
                employee_name VARCHAR(255),
                employee_email VARCHAR(255) NOT NULL,
                department VARCHAR(255),
                app_name VARCHAR(255) NOT NULL,
                risk_tier VARCHAR(100) NOT NULL,
                is_critical BOOLEAN DEFAULT FALSE,
                scopes_count INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (timestamp, employee_email, app_name)
            );

            CREATE TABLE IF NOT EXISTS mailbox_forwarding_rules (
                id SERIAL PRIMARY KEY,
                timestamp VARCHAR(50) NOT NULL,
                employee_name VARCHAR(255),
                employee_email VARCHAR(255) NOT NULL,
                department VARCHAR(255),
                destination VARCHAR(255) NOT NULL,
                setup_type VARCHAR(100) NOT NULL,
                is_external BOOLEAN DEFAULT FALSE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (employee_email, destination)
            );

            CREATE TABLE IF NOT EXISTS license_reclamation_pipeline (
                email VARCHAR(255) PRIMARY KEY,
                name VARCHAR(255),
                department VARCHAR(255),
                batch VARCHAR(100),
                status VARCHAR(100) NOT NULL,
                days_inactive INT,
                last_login VARCHAR(100),
                action VARCHAR(255) NOT NULL,
                estimated_annual_waste NUMERIC(10, 2) DEFAULT 0.0,
                annual_cost_php NUMERIC(10, 2) DEFAULT 0.0,
                prorated_recovery_php NUMERIC(10, 2) DEFAULT 0.0,
                remaining_days_contract INT DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_dm_date_email ON daily_metrics (date, email);
            CREATE INDEX IF NOT EXISTS idx_ud_dept ON user_departments (department);
            CREATE INDEX IF NOT EXISTS idx_pwd_target ON password_reset_events (target_email);
            CREATE INDEX IF NOT EXISTS idx_dlp_owner ON dlp_file_exposures (owner_email);

            -- Progressive table migrations
            ALTER TABLE department_governance ADD COLUMN IF NOT EXISTS suspended_seats INT DEFAULT 0;
            ALTER TABLE department_governance ADD COLUMN IF NOT EXISTS admin_users_count INT DEFAULT 0;
            ALTER TABLE department_governance ADD COLUMN IF NOT EXISTS admin_resets INT DEFAULT 0;
            ALTER TABLE department_governance ADD COLUMN IF NOT EXISTS self_resets INT DEFAULT 0;
            ALTER TABLE department_governance ADD COLUMN IF NOT EXISTS total_password_resets INT DEFAULT 0;
            ALTER TABLE department_governance ADD COLUMN IF NOT EXISTS two_factor_coverage_pct NUMERIC(5, 2) DEFAULT 0.0;

            ALTER TABLE organization_governance_pool ADD COLUMN IF NOT EXISTS assigned_licenses INT DEFAULT 0;

            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN DEFAULT FALSE;
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS is_delegated_admin BOOLEAN DEFAULT FALSE;
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS privilege_tier VARCHAR(100) DEFAULT 'Standard User';
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS admin_resets INT DEFAULT 0;
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS self_resets INT DEFAULT 0;
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS total_password_resets INT DEFAULT 0;
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS last_password_reset_date VARCHAR(100);
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS password_risk_category VARCHAR(100) DEFAULT '⚪ Stable (0 Resets)';
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS password_recommendation VARCHAR(255) DEFAULT 'None (Good Security Habits)';
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS external_shares_count INT DEFAULT 0;
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS public_links_count INT DEFAULT 0;
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS oauth_apps_count INT DEFAULT 0;
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS critical_oauth_apps_count INT DEFAULT 0;
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS has_forwarding BOOLEAN DEFAULT FALSE;
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS forwarding_target VARCHAR(255);
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS days_inactive INT;
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS cloud_maturity_tier VARCHAR(100) DEFAULT 'Needs Enablement';
            ALTER TABLE user_departments ADD COLUMN IF NOT EXISTS license_waste_status VARCHAR(100) DEFAULT 'Active';
        '''))


def match_department_and_batch(text_to_match, user_email=""):
    clean_email = (user_email or '').lower().strip()
    if any(prefix in clean_email for prefix in ['it@', 'tech@', 'sysadmin@']) or clean_email == ADMIN_EMAIL.lower():
        return 'IT Department', 'IT'
    if any(prefix in clean_email for prefix in ['ceo@', 'president@', 'board@', 'exec@', 'admin@']):
        return 'Management', 'Executive'

    if not text_to_match:
        return 'Operations (Unassigned)', 'General'

    raw_clean = text_to_match.lower().replace('&', 'and').replace('/', ' ')
    raw_clean = re.sub(r'[^a-z0-9\s]', ' ', raw_clean).strip()
    words = raw_clean.split()

    if 'credit and collection' in raw_clean or 'credit & collection' in raw_clean or 'collection' in words or 'credit' in words:
        return 'Credit and Collection', 'Batch 1'
    if 'warehouse' in raw_clean or 'logistics' in words or 'inventory' in words:
        return 'Warehouse', 'Batch 2'
    if 'marketing' in raw_clean or 'mktg' in words or 'branding' in words:
        return 'Marketing', 'Batch 3'
    if 'accounting' in raw_clean or 'acct' in words:
        return 'Accounting', 'Batch 1'
    if 'finance' in raw_clean or 'fa' in words:
        return 'Finance', 'Batch 1'

    for canonical_name, meta in DEPARTMENT_TAXONOMY.items():
        if canonical_name.lower() in raw_clean:
            return canonical_name, meta['batch']
        for alias in meta['aliases']:
            alias_clean = alias.lower().replace('&', 'and')
            if alias_clean in raw_clean or alias_clean in words:
                return canonical_name, meta['batch']

    return text_to_match.strip(), 'General'


def extract_user_department(google_user, existing_storage_map=None):
    email = google_user.get('primaryEmail', '').lower()
    raw_dept = None

    orgs = google_user.get('organizations', [])
    for org in orgs:
        if org.get('primary'):
            raw_dept = org.get('department') or org.get('title') or org.get('costCenter')
            if raw_dept and raw_dept.strip():
                break

    if not raw_dept:
        for org in orgs:
            d = org.get('department') or org.get('title')
            if d and d.strip():
                raw_dept = d.strip()
                break

    if not raw_dept:
        ou_path = google_user.get('orgUnitPath', '').strip('/')
        if ou_path:
            raw_dept = ou_path.split('/')[-1]

    if (not raw_dept or 'unassigned' in raw_dept.lower()) and existing_storage_map:
        if email in existing_storage_map:
            stored_dept = existing_storage_map[email].get('department')
            if stored_dept and 'unassigned' not in stored_dept.lower():
                raw_dept = stored_dept

    return match_department_and_batch(raw_dept, user_email=email)


def preflight_reconciliation_check():
    print("\n" + "=" * 75)
    print(" [STAGE 1] PRE-FLIGHT RECONCILIATION & STORAGE BACKUP")
    print("=" * 75)

    creds = get_delegated_credentials()
    dir_service = build('admin', 'directory_v1', credentials=creds, cache_discovery=False)

    real_customer_id = 'my_customer'
    try:
        admin_user = dir_service.users().get(userKey=ADMIN_EMAIL).execute(num_retries=2)
        c_id = admin_user.get('customerId')
        if c_id:
            real_customer_id = c_id
            print(f"[*] Resolved Internal Google Customer ID -> {real_customer_id}")
    except Exception as e:
        print(f"    [Customer ID Note]: {e}")

    google_users = {}
    page_token = None
    print("[*] Contacting Google Directory API for live domain accounts...")
    while True:
        res = dir_service.users().list(
            customer='my_customer',
            projection='full',
            maxResults=500,
            pageToken=page_token
        ).execute(num_retries=5)
        for u in res.get('users', []):
            em = u.get('primaryEmail', '').lower()
            if em:
                google_users[em] = u
        page_token = res.get('nextPageToken')
        if not page_token:
            break

    print(f"    --> Live Google Workspace Accounts (Active + Suspended): {len(google_users)}")

    supabase_users = {}
    with db_engine.connect() as conn:
        try:
            u_rows = conn.execute(text("""
                                       SELECT u.email,
                                              u.name,
                                              u.department,
                                              u.batch,
                                              u.is_enrolled_in_2sv,
                                              u.drive_bytes,
                                              u.gmail_bytes
                                       FROM user_departments u;
                                       """)).fetchall()
            for r in u_rows:
                supabase_users[r[0].lower()] = {
                    'name': r[1], 'department': r[2], 'batch': r[3], '2fa': r[4],
                    'drive_bytes': int(r[5] or 0), 'gmail_bytes': int(r[6] or 0)
                }
        except Exception as e:
            print(f"    [Supabase Notice]: {e}")

    total_prev_gmail = sum(u['gmail_bytes'] for u in supabase_users.values()) / (1024 ** 3)
    total_prev_drive = sum(u['drive_bytes'] for u in supabase_users.values()) / (1024 ** 3)
    print(f"    --> Current stored usage: {total_prev_gmail:.1f} GB Gmail, {total_prev_drive:.1f} GB Drive")
    print("=" * 75)

    return google_users, supabase_users, real_customer_id


def fetch_realtime_user_storage(user_email):
    try:
        user_creds = get_delegated_credentials(subject_email=user_email)
        u_drive = build('drive', 'v3', credentials=user_creds, cache_discovery=False)
        about = u_drive.about().get(fields="storageQuota").execute(num_retries=2)
        quota = about.get('storageQuota', {})
        usage_drive = int(quota.get('usageInDrive', 0))
        usage_trash = int(quota.get('usageInDriveTrash', 0))
        return usage_drive + usage_trash
    except Exception:
        return 0


def probe_latest_user_storage_from_google(creds):
    print("[*] Probing Google Reports API for live Gmail quota usage...")
    rep_service = build('admin', 'reports_v1', credentials=creds, cache_discovery=False)
    today = datetime.date.today()

    storage_params = 'accounts:gmail_used_quota_in_mb'
    user_gmail_map = {}

    for days_back in range(2, 15):
        test_date = (today - datetime.timedelta(days=days_back)).isoformat()
        try:
            page_token = None
            total_found = 0
            while True:
                res = rep_service.userUsageReport().get(
                    userKey='all', date=test_date, parameters=storage_params, pageToken=page_token
                ).execute(num_retries=2)

                reports = res.get('usageReports', [])
                for r in reports:
                    em = r.get('entity', {}).get('userEmail', '').lower()
                    pms = {p['name']: p for p in r.get('parameters', [])}
                    g_mb = int(pms.get('accounts:gmail_used_quota_in_mb', {}).get('intValue', 0))
                    if g_mb > 0:
                        user_gmail_map[em] = g_mb * 1024 * 1024
                        total_found += 1

                page_token = res.get('nextPageToken')
                if not page_token:
                    break

            if total_found > 0:
                print(f"    [+] Retrieved Gmail storage for {total_found} accounts from date: {test_date}.")
                return user_gmail_map
        except Exception:
            continue

    return user_gmail_map


def sync_governance_and_security_telemetry(rep_service, user_directory):
    """
    Exhaustively scans Google Workspace audit telemetry (180 days) and persists:
    1. Password Reset Ledger -> password_reset_events
    2. DLP External File Sharing -> dlp_file_exposures
    3. Shadow IT OAuth Grants -> oauth_app_authorizations
    4. Mailbox Auto-Forwarding Rules -> mailbox_forwarding_rules
    """
    print("[*] Ingesting 180-Day Password Resets, DLP Exposures, Shadow IT, and Forwarding telemetry...")

    password_events = []
    dlp_events = []
    oauth_events = []
    forwarding_events = []

    # 1. PASSWORD RESETS (ADMIN CONSOLE)
    try:
        p_tok = None
        while True:
            res = rep_service.activities().list(
                userKey='all', applicationName='admin', eventName='CHANGE_PASSWORD', maxResults=100, pageToken=p_tok
            ).execute(num_retries=2)
            for item in res.get('items', []):
                admin_actor = item.get('actor', {}).get('email', '').lower().strip()
                t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                for ev in item.get('events', []):
                    pms = {p['name']: p.get('value') or p.get('stringValue') for p in ev.get('parameters', [])}
                    target_em = (pms.get('USER_EMAIL') or pms.get('TARGET_USER') or '').lower().strip()
                    if target_em in user_directory:
                        u = user_directory[target_em]
                        u['admin_resets'] += 1
                        u['total_password_resets'] += 1
                        if not u['last_password_reset_date'] or t_str[:10] > u['last_password_reset_date']:
                            u['last_password_reset_date'] = t_str[:10]

                        password_events.append({
                            'timestamp': t_str,
                            'target_email': target_em,
                            'target_name': u['name'],
                            'department': u['department'],
                            'reset_type': 'IT Admin Forced Reset',
                            'initiator': admin_actor or 'Admin Console'
                        })
            p_tok = res.get('nextPageToken')
            if not p_tok:
                break
    except Exception as e:
        print(f"    [!] Admin Password Sync Note: {e}")

    # 2. PASSWORD CHANGES (SELF-SERVICE / USER RECOVERIES)
    try:
        p_tok = None
        while True:
            res = rep_service.activities().list(
                userKey='all', applicationName='login', maxResults=100, pageToken=p_tok
            ).execute(num_retries=2)
            for item in res.get('items', []):
                user_actor = item.get('actor', {}).get('email', '').lower().strip()
                t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                for ev in item.get('events', []):
                    ev_name = ev.get('name', '')
                    if ev_name in ['password_change', 'account_recovery_password_reset']:
                        if user_actor in user_directory:
                            u = user_directory[user_actor]
                            u['self_resets'] += 1
                            u['total_password_resets'] += 1
                            if not u['last_password_reset_date'] or t_str[:10] > u['last_password_reset_date']:
                                u['last_password_reset_date'] = t_str[:10]

                            lbl = 'Self-Service Recovery' if ev_name == 'account_recovery_password_reset' else 'User Password Change'
                            password_events.append({
                                'timestamp': t_str,
                                'target_email': user_actor,
                                'target_name': u['name'],
                                'department': u['department'],
                                'reset_type': lbl,
                                'initiator': user_actor
                            })
            p_tok = res.get('nextPageToken')
            if not p_tok:
                break
    except Exception as e:
        print(f"    [!] Self Password Sync Note: {e}")

    # 3. DRIVE DLP & EXTERNAL SHARING
    dlp_target_events = ['change_user_access', 'change_document_visibility', 'acl_change']
    for ev_name in dlp_target_events:
        try:
            d_tok = None
            while True:
                d_res = rep_service.activities().list(
                    userKey='all',
                    applicationName='drive',
                    eventName=ev_name,
                    maxResults=100,
                    pageToken=d_tok
                ).execute(num_retries=2)

                for item in d_res.get('items', []):
                    actor_em = item.get('actor', {}).get('email', '').lower().strip()
                    t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                    u_info = user_directory.get(actor_em, {'name': actor_em, 'department': 'Operations'})

                    for ev in item.get('events', []):
                        pms = {p['name']: p.get('value') or p.get('stringValue') for p in ev.get('parameters', [])}
                        doc_title = pms.get('doc_title') or pms.get('title') or 'Untitled Document'
                        doc_type = pms.get('doc_type') or 'file'
                        target_u = (pms.get('target_user') or pms.get('user') or '').lower().strip()
                        vis = pms.get('visibility') or ''

                        is_public = (vis in ['people_with_link', 'public']) or ('link' in vis.lower())
                        is_external = bool(target_u and ALLOWED_DOMAIN not in target_u and '@' in target_u)

                        if is_public or is_external:
                            if actor_em in user_directory:
                                if is_public:
                                    user_directory[actor_em]['public_links_count'] += 1
                                if is_external:
                                    user_directory[actor_em]['external_shares_count'] += 1

                            dom = target_u.split('@')[-1] if is_external else 'public'
                            dlp_events.append({
                                'timestamp': t_str,
                                'owner_name': u_info['name'],
                                'owner_email': actor_em,
                                'department': u_info['department'],
                                'doc_title': doc_title,
                                'doc_type': doc_type,
                                'recipient': target_u or 'public',
                                'recipient_domain': dom,
                                'visibility': vis or ('public_link' if is_public else 'external'),
                                'is_public_link': is_public
                            })
                d_tok = d_res.get('nextPageToken')
                if not d_tok:
                    break
        except Exception as e:
            print(f"    [!] DLP Scan ({ev_name}) Note: {e}")

    # 4. SHADOW IT OAUTH GRANTS
    try:
        t_tok = None
        while True:
            res = rep_service.activities().list(
                userKey='all', applicationName='token', maxResults=100, pageToken=t_tok
            ).execute(num_retries=2)
            for item in res.get('items', []):
                actor_em = item.get('actor', {}).get('email', '').lower().strip()
                t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                u_info = user_directory.get(actor_em, {'name': actor_em, 'department': 'Operations'})

                for ev in item.get('events', []):
                    if ev.get('name') == 'authorize':
                        pms = {p['name']: p for p in ev.get('parameters', [])}
                        app_name = pms.get('app_name', {}).get('value', 'External Application')
                        scope_list = pms.get('scope_data', {}).get('multiValue', []) or pms.get('scope', {}).get(
                            'multiValue', [])

                        has_mail = any('mail.google.com' in s or 'gmail' in s for s in scope_list)
                        has_drive = any('auth/drive' in s for s in scope_list)

                        if has_mail or has_drive:
                            risk_tier = "🔴 CRITICAL: Reads Mail/Drive"
                            is_crit = True
                        else:
                            risk_tier = "🟢 LOW: Standard Sign-In"
                            is_crit = False

                        if actor_em in user_directory:
                            user_directory[actor_em]['oauth_apps_count'] += 1
                            if is_crit:
                                user_directory[actor_em]['critical_oauth_apps_count'] += 1

                        oauth_events.append({
                            'timestamp': t_str,
                            'employee_name': u_info['name'],
                            'employee_email': actor_em,
                            'department': u_info['department'],
                            'app_name': app_name,
                            'risk_tier': risk_tier,
                            'is_critical': is_crit,
                            'scopes_count': len(scope_list)
                        })
            t_tok = res.get('nextPageToken')
            if not t_tok:
                break
    except Exception as e:
        print(f"    [!] Shadow IT Sync Note: {e}")

    # 5. MAILBOX AUTO-FORWARDING
    try:
        u_tok = None
        while True:
            res = rep_service.activities().list(
                userKey='all', applicationName='user_accounts', maxResults=100, pageToken=u_tok
            ).execute(num_retries=2)
            for item in res.get('items', []):
                actor_em = item.get('actor', {}).get('email', '').lower().strip()
                t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                u_info = user_directory.get(actor_em, {'name': actor_em, 'department': 'Operations'})
                for ev in item.get('events', []):
                    if 'forward' in ev.get('name', '').lower():
                        pms = {p['name']: p for p in ev.get('parameters', [])}
                        dest = pms.get('forwarding_address', {}).get('value', '') or pms.get('email_address', {}).get(
                            'value', 'External')
                        is_ext = (ALLOWED_DOMAIN not in dest and '@' in dest)
                        if actor_em in user_directory:
                            user_directory[actor_em]['has_forwarding'] = True
                            user_directory[actor_em]['forwarding_target'] = dest
                        forwarding_events.append({
                            'timestamp': t_str,
                            'employee_name': u_info['name'],
                            'employee_email': actor_em,
                            'department': u_info['department'],
                            'destination': dest,
                            'setup_type': 'User Self-Service Forwarding',
                            'is_external': is_ext
                        })
            u_tok = res.get('nextPageToken')
            if not u_tok:
                break
    except Exception as e:
        print(f"    [!] Forwarding Sync Note: {e}")

    # PERSIST TO SUPABASE
    with db_engine.begin() as conn:
        if password_events:
            conn.execute(text('''
                              INSERT INTO password_reset_events (timestamp, target_email, target_name, department,
                                                                 reset_type, initiator)
                              VALUES (:timestamp, :target_email, :target_name, :department, :reset_type,
                                      :initiator) ON CONFLICT (timestamp, target_email, reset_type) DO NOTHING;
                              '''), password_events)

        if dlp_events:
            conn.execute(text('''
                              INSERT INTO dlp_file_exposures (timestamp, owner_name, owner_email, department, doc_title,
                                                              doc_type, recipient, recipient_domain, visibility,
                                                              is_public_link)
                              VALUES (:timestamp, :owner_name, :owner_email, :department, :doc_title, :doc_type,
                                      :recipient, :recipient_domain, :visibility,
                                      :is_public_link) ON CONFLICT (timestamp, owner_email, doc_title, recipient) DO NOTHING;
                              '''), dlp_events)

        if oauth_events:
            conn.execute(text('''
                              INSERT INTO oauth_app_authorizations (timestamp, employee_name, employee_email,
                                                                    department, app_name, risk_tier, is_critical,
                                                                    scopes_count)
                              VALUES (:timestamp, :employee_name, :employee_email, :department, :app_name, :risk_tier,
                                      :is_critical,
                                      :scopes_count) ON CONFLICT (timestamp, employee_email, app_name) DO NOTHING;
                              '''), oauth_events)

        if forwarding_events:
            conn.execute(text('''
                              INSERT INTO mailbox_forwarding_rules (timestamp, employee_name, employee_email,
                                                                    department, destination, setup_type, is_external)
                              VALUES (:timestamp, :employee_name, :employee_email, :department, :destination,
                                      :setup_type, :is_external) ON CONFLICT (employee_email, destination) DO
                              UPDATE SET
                                  timestamp = EXCLUDED.timestamp,
                                  destination = EXCLUDED.destination,
                                  is_external = EXCLUDED.is_external,
                                  updated_at = CURRENT_TIMESTAMP;
                              '''), forwarding_events)

    print(
        f"    [+] Saved {len(password_events)} password events, {len(dlp_events)} DLP exposures, {len(oauth_events)} OAuth app grants, and {len(forwarding_events)} forwarding rules.")


def sync_license_reclamation_pipeline(user_directory, assigned_license_emails):
    """Calculates pro-rated Kollab contract seat waste in Philippine Peso (PHP)."""
    print(
        f"[*] Reconciling Kollab License Pipeline in PHP (Annual: ₱{KOLLAB_ANNUAL_COST_PHP:,.2f} | Daily: ₱{KOLLAB_DAILY_COST_PHP:.2f})...")

    today = datetime.date.today()
    try:
        renewal_date = datetime.date.fromisoformat(KOLLAB_RENEWAL_DATE_STR)
    except Exception:
        renewal_date = today + datetime.timedelta(days=180)

    remaining_days = max(0, (renewal_date - today).days)
    prorated_seat_recovery = round(remaining_days * KOLLAB_DAILY_COST_PHP, 2)

    reclaim_records = []

    for em, u in user_directory.items():
        has_lic = em in assigned_license_emails
        if not has_lic:
            continue

        is_susp = u['is_suspended']
        days_inact = u.get('days_inactive')
        last_login = u.get('last_login_time', 'Never')

        annual_waste_php = 0.0
        prorated_php = 0.0

        if is_susp:
            status = 'Suspended Account'
            action = '🔴 Revoke License (Immediate Pro-rated Credit)'
            annual_waste_php = KOLLAB_ANNUAL_COST_PHP
            prorated_php = prorated_seat_recovery
            u['license_waste_status'] = 'Suspended with Paid License'
        elif days_inact is not None and days_inact >= 60:
            status = f'Dormant Account ({days_inact}d inactive)'
            action = '🟡 Reclaim Seat for Next Onboarding'
            annual_waste_php = KOLLAB_ANNUAL_COST_PHP
            prorated_php = prorated_seat_recovery
            u['license_waste_status'] = 'Dormant (>60d Inactive)'
        elif not last_login or last_login == 'Never':
            status = 'Never Logged In'
            action = '🟡 Onboarding Failure / Reassign License'
            annual_waste_php = KOLLAB_ANNUAL_COST_PHP
            prorated_php = prorated_seat_recovery
            u['license_waste_status'] = 'Never Logged In'
        else:
            status = 'Active Utilization'
            action = 'Optimal'
            annual_waste_php = 0.0
            prorated_php = 0.0
            u['license_waste_status'] = 'Optimal Active'

        if annual_waste_php > 0:
            reclaim_records.append({
                'email': em,
                'name': u['name'],
                'department': u['department'],
                'batch': u['batch'],
                'status': status,
                'days_inactive': days_inact,
                'last_login': last_login,
                'action': action,
                'estimated_annual_waste': annual_waste_php,
                'annual_cost_php': annual_waste_php,
                'prorated_recovery_php': prorated_php,
                'remaining_days_contract': remaining_days
            })

    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM license_reclamation_pipeline;"))
        if reclaim_records:
            conn.execute(text('''
                              INSERT INTO license_reclamation_pipeline
                              (email, name, department, batch, status, days_inactive, last_login, action,
                               estimated_annual_waste, annual_cost_php, prorated_recovery_php, remaining_days_contract,
                               updated_at)
                              VALUES (:email, :name, :department, :batch, :status, :days_inactive, :last_login, :action,
                                      :estimated_annual_waste, :annual_cost_php, :prorated_recovery_php,
                                      :remaining_days_contract, CURRENT_TIMESTAMP);
                              '''), reclaim_records)

    print(
        f"    [+] Logged {len(reclaim_records)} reclamation candidates. Total Pro-rated Recovery: ₱{sum(r['prorated_recovery_php'] for r in reclaim_records):,.2f}")


def is_authentic_meet_recording(file_name, parents=None, description=None, meet_folder_ids=None):
    parents = parents or []
    meet_folder_ids = meet_folder_ids or set()

    if any(p in meet_folder_ids for p in parents):
        return True

    desc = (description or '').lower()
    if 'meet' in desc or 'google meet' in desc:
        return True

    if re.search(r'\(\d{4}-\d{2}-\d{2}', file_name):
        return True

    if 'meet recording' in file_name.lower() or 'meet_recording' in file_name.lower():
        return True

    return False


def fetch_single_user_meet_recordings(user_email, user_info):
    recordings = []
    try:
        user_creds = get_delegated_credentials(subject_email=user_email)
        u_drive = build('drive', 'v3', credentials=user_creds, cache_discovery=False)

        meet_folder_ids = set()
        folder_res = u_drive.files().list(
            q="mimeType = 'application/vnd.google-apps.folder' and name = 'Meet Recordings' and trashed = false",
            fields="files(id)",
            pageSize=10
        ).execute(num_retries=2)
        for fld in folder_res.get('files', []):
            meet_folder_ids.add(fld.get('id'))

        query = "mimeType = 'video/mp4' and trashed = false"
        page_tok = None

        while True:
            res = u_drive.files().list(
                q=query,
                fields="nextPageToken, files(id, name, size, createdTime, webViewLink, parents, description, videoMediaMetadata)",
                pageSize=100,
                pageToken=page_tok
            ).execute(num_retries=2)

            for f in res.get('files', []):
                fname = f.get('name', '')
                parents = f.get('parents', [])
                desc = f.get('description', '')

                if not is_authentic_meet_recording(fname, parents, desc, meet_folder_ids):
                    continue

                fid = f.get('id')
                v_meta = f.get('videoMediaMetadata', {})
                dur_mins = round(int(v_meta.get('durationMillis', 0)) / (1000 * 60))

                recordings.append({
                    'recording_id': fid,
                    'title': fname,
                    'organizer_email': user_email,
                    'organizer_name': user_info.get('name', user_email),
                    'department': user_info.get('department', 'Operations'),
                    'batch': user_info.get('batch', 'General'),
                    'size_bytes': int(f.get('size', 0)),
                    'duration_minutes': dur_mins,
                    'created_at': f.get('createdTime'),
                    'web_view_link': f.get('webViewLink') or '#'
                })

            page_tok = res.get('nextPageToken')
            if not page_tok:
                break

    except Exception:
        pass

    return recordings


def sync_all_users_google_meet_recordings(user_directory, admin_creds):
    print("[*] Discovering Google Meet recordings across enterprise drives...")
    all_discovered = {}

    try:
        admin_drive = build('drive', 'v3', credentials=admin_creds, cache_discovery=False)
        shared_res = admin_drive.files().list(
            q="mimeType = 'video/mp4' and trashed = false",
            corpora='allDrives',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            fields="files(id, name, size, createdTime, webViewLink, owners, parents, description, videoMediaMetadata)",
            pageSize=100
        ).execute(num_retries=2)

        for f in shared_res.get('files', []):
            fname = f.get('name', '')
            parents = f.get('parents', [])
            desc = f.get('description', '')

            if not is_authentic_meet_recording(fname, parents, desc, set()):
                continue

            fid = f.get('id')
            owners = f.get('owners', [])
            owner_em = owners[0].get('emailAddress', '').lower() if owners else ADMIN_EMAIL.lower()
            owner_name = owners[0].get('displayName', owner_em) if owners else 'Drive Organizer'
            dept = user_directory.get(owner_em, {}).get('department', 'Operations')
            batch = user_directory.get(owner_em, {}).get('batch', 'General')
            v_meta = f.get('videoMediaMetadata', {})
            dur_mins = round(int(v_meta.get('durationMillis', 0)) / (1000 * 60))

            all_discovered[fid] = {
                'recording_id': fid,
                'title': fname,
                'organizer_email': owner_em,
                'organizer_name': owner_name,
                'department': dept,
                'batch': batch,
                'size_bytes': int(f.get('size', 0)),
                'duration_minutes': dur_mins,
                'created_at': f.get('createdTime'),
                'web_view_link': f.get('webViewLink') or '#'
            }
    except Exception as e:
        print(f"    [Shared Drive Recording Scan Note]: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_email = {
            executor.submit(fetch_single_user_meet_recordings, email, info): email
            for email, info in user_directory.items()
            if not info.get('is_suspended', False)
        }
        for future in concurrent.futures.as_completed(future_to_email):
            recs = future.result()
            for r in recs:
                all_discovered[r['recording_id']] = r

    recordings_list = list(all_discovered.values())

    if recordings_list:
        with db_engine.begin() as conn:
            conn.execute(text('''
                              INSERT INTO meet_recordings
                              (recording_id, title, organizer_email, organizer_name, department, batch, size_bytes,
                               duration_minutes, created_at, web_view_link, updated_at)
                              VALUES (:recording_id, :title, :organizer_email, :organizer_name, :department, :batch,
                                      :size_bytes, :duration_minutes, :created_at, :web_view_link,
                                      CURRENT_TIMESTAMP) ON CONFLICT (recording_id) DO
                              UPDATE SET
                                  title = EXCLUDED.title,
                                  organizer_name = EXCLUDED.organizer_name,
                                  department = EXCLUDED.department,
                                  size_bytes = EXCLUDED.size_bytes,
                                  duration_minutes = EXCLUDED.duration_minutes,
                                  web_view_link = EXCLUDED.web_view_link,
                                  updated_at = CURRENT_TIMESTAMP;
                              '''), recordings_list)


def sync_cross_department_matrix(creds, user_directory):
    print("[*] Auditing multi-channel cross-department collaboration telemetry...")
    rep_service = build('admin', 'reports_v1', credentials=creds, cache_discovery=False)
    drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    today = datetime.date.today().isoformat()

    events_to_insert = []

    # 1. Shared Drive Cross-Membership
    try:
        drives_res = drive_service.drives().list(pageSize=100, useDomainAdminAccess=True).execute(num_retries=2)
        for d in drives_res.get('drives', []):
            d_id = d.get('id')
            d_name = d.get('name')
            drive_dept, _ = match_department_and_batch(d_name)

            if 'Unassigned' in drive_dept:
                continue

            perms_res = drive_service.permissions().list(
                fileId=d_id, supportsAllDrives=True, useDomainAdminAccess=True,
                fields="permissions(displayName,emailAddress,role)"
            ).execute(num_retries=2)

            for p in perms_res.get('permissions', []):
                mem_email = (p.get('emailAddress') or '').lower().strip()
                if not mem_email or ALLOWED_DOMAIN not in mem_email:
                    continue

                mem_info = user_directory.get(mem_email, {})
                mem_name = mem_info.get('name', mem_email)
                mem_dept = mem_info.get('department', 'Operations (Unassigned)')

                if mem_dept != drive_dept and 'Unassigned' not in mem_dept:
                    events_to_insert.append({
                        'actor_email': mem_email,
                        'actor_name': mem_name,
                        'source_department': mem_dept,
                        'target_email': f"drive.{d_id[:12]}@{ALLOWED_DOMAIN}",
                        'target_department': drive_dept,
                        'interaction_type': 'shared_drive_access',
                        'audit_date': today
                    })
    except Exception as e:
        print(f"    [Shared Drive Collab Note]: {e}")

    # 2. Drive Shares & Edits
    try:
        results = rep_service.activities().list(
            userKey='all', applicationName='drive', maxResults=150
        ).execute(num_retries=2)

        for item in results.get('items', []):
            actor_email = item.get('actor', {}).get('email', '').lower().strip()
            actor_info = user_directory.get(actor_email, {})
            actor_name = actor_info.get('name', actor_email)
            actor_dept = actor_info.get('department', 'Operations (Unassigned)')

            for event in item.get('events', []):
                params = {p['name']: p for p in event.get('parameters', [])}
                target_user = params.get('target_user', {}).get('stringValue', '').lower().strip()
                owner_user = params.get('owner', {}).get('stringValue', '').lower().strip()

                counterpart = target_user or (owner_user if owner_user and owner_user != actor_email else None)
                if counterpart and ALLOWED_DOMAIN in counterpart and counterpart != actor_email:
                    target_info = user_directory.get(counterpart, {})
                    target_dept = target_info.get('department', 'Operations (Unassigned)')

                    if actor_dept != target_dept and 'Unassigned' not in actor_dept and 'Unassigned' not in target_dept:
                        events_to_insert.append({
                            'actor_email': actor_email,
                            'actor_name': actor_name,
                            'source_department': actor_dept,
                            'target_email': counterpart,
                            'target_department': target_dept,
                            'interaction_type': 'drive_collaboration',
                            'audit_date': today
                        })
    except Exception as e:
        print(f"    [Drive Activity Collab Note]: {e}")

    # 3. Calendar Invites
    try:
        cal_res = rep_service.activities().list(
            userKey='all', applicationName='calendar', maxResults=150
        ).execute(num_retries=2)

        for item in cal_res.get('items', []):
            actor_email = item.get('actor', {}).get('email', '').lower().strip()
            actor_info = user_directory.get(actor_email, {})
            actor_name = actor_info.get('name', actor_email)
            actor_dept = actor_info.get('department', 'Operations (Unassigned)')

            for ev in item.get('events', []):
                pms = {p['name']: p for p in ev.get('parameters', [])}
                guests = pms.get('guest', {}).get('multiValue', []) or pms.get('attendees', {}).get('multiValue', [])

                for g in guests:
                    g_em = g.lower().strip()
                    if g_em and g_em != actor_email and ALLOWED_DOMAIN in g_em:
                        target_info = user_directory.get(g_em, {})
                        target_dept = target_info.get('department', 'Operations (Unassigned)')

                        if actor_dept != target_dept and 'Unassigned' not in actor_dept and 'Unassigned' not in target_dept:
                            events_to_insert.append({
                                'actor_email': actor_email,
                                'actor_name': actor_name,
                                'source_department': actor_dept,
                                'target_email': g_em,
                                'target_department': target_dept,
                                'interaction_type': 'meeting_invite',
                                'audit_date': today
                            })
    except Exception as e:
        print(f"    [Calendar Collab Note]: {e}")

    if events_to_insert:
        with db_engine.begin() as conn:
            conn.execute(text('''
                              INSERT INTO user_collaboration_events
                              (actor_email, actor_name, source_department, target_email, target_department,
                               interaction_type, interaction_count, audit_date, updated_at)
                              VALUES (:actor_email, :actor_name, :source_department, :target_email, :target_department,
                                      :interaction_type, 1, :audit_date, CURRENT_TIMESTAMP) ON CONFLICT (actor_email, target_email, audit_date, interaction_type) 
                DO
                              UPDATE SET
                                  interaction_count = user_collaboration_events.interaction_count + 1,
                                  updated_at = CURRENT_TIMESTAMP;
                              '''), events_to_insert)

            conn.execute(text('''
                              INSERT INTO cross_dept_collaboration (source_department, target_department,
                                                                    interaction_type, interaction_count, audit_date,
                                                                    updated_at)
                              SELECT source_department,
                                     target_department,
                                     interaction_type,
                                     SUM(interaction_count),
                                     audit_date,
                                     CURRENT_TIMESTAMP
                              FROM user_collaboration_events
                              WHERE audit_date = :date
                              GROUP BY source_department, target_department, interaction_type, audit_date ON CONFLICT (source_department, target_department, audit_date, interaction_type) 
                DO
                              UPDATE SET
                                  interaction_count = EXCLUDED.interaction_count,
                                  updated_at = CURRENT_TIMESTAMP;
                              '''), {'date': today})

        print(f"    [+] Saved {len(events_to_insert)} cross-department collaboration events to Supabase.")


def sync_google_licensing_data(creds, google_users, real_customer_id):
    print("[*] Interrogating Google Licensing API for assigned domain seats (with pagination)...")
    assigned_emails = set()
    page_token = None
    page_count = 0

    try:
        lic_service = build('licensing', 'v1', credentials=creds, cache_discovery=False)
        while True:
            result = lic_service.licenseAssignments().listForProduct(
                productId='Google-Apps',
                customerId=ALLOWED_DOMAIN,
                maxResults=100,
                pageToken=page_token
            ).execute(num_retries=2)

            items = result.get('items', [])
            page_count += 1
            for item in items:
                u_email = item.get('userId', '').lower().strip()
                if u_email:
                    assigned_emails.add(u_email)

            page_token = result.get('nextPageToken')
            if not page_token:
                break

        print(f"    [+] Traversed {page_count} page(s). Total live assigned licenses: {len(assigned_emails)}")
    except Exception as e:
        print(f"    [Licensing API Warning]: {e}")
        assigned_emails = set(google_users.keys())

    total_purchased = TOTAL_CONTRACT_LICENSES
    customer_quota_gb = ORGANIZATION_STORAGE_QUOTA_GB
    customer_used_gb = 0.0
    settled_report_date = None

    rep_service = build('admin', 'reports_v1', credentials=creds, cache_discovery=False)
    today = datetime.date.today()

    for days_back in range(2, 15):
        test_date = (today - datetime.timedelta(days=days_back)).isoformat()
        try:
            cust_res = rep_service.customerUsageReports().get(
                date=test_date, customerId=real_customer_id
            ).execute(num_retries=1)

            reports = cust_res.get('usageReports', [])
            if reports:
                pms = {p['name']: p for p in reports[0].get('parameters', [])}
                auth_lic = extract_param_val(pms, 'accounts:num_authorized_licenses')
                total_q_mb = extract_param_val(pms, 'accounts:total_quota_in_mb')
                used_q_mb = extract_param_val(pms, 'accounts:used_quota_in_mb')

                if auth_lic > 0:
                    total_purchased = auth_lic
                    print(f"    [+] Dynamic capacity from Google Reports API: {total_purchased} Purchased Seats.")
                else:
                    total_purchased = TOTAL_CONTRACT_LICENSES
                    print(f"    [+] Using contracted license pool: {total_purchased} Purchased Seats.")

                if total_q_mb > 0:
                    customer_quota_gb = round(total_q_mb / 1000.0, 2)
                if used_q_mb > 0:
                    customer_used_gb = round(used_q_mb / 1000.0, 2)

                settled_report_date = test_date
                break
        except Exception:
            continue

    return assigned_emails, total_purchased, customer_quota_gb, customer_used_gb, settled_report_date


def sync_department_governance_metrics(user_directory):
    """
    Aggregates departmental governance, admin seat counts, 2SV compliance,
    and 180-day reset volumes directly into department_governance.
    """
    print("[*] Aggregating departmental governance metrics into Supabase...")
    dept_map = {}

    for info in user_directory.values():
        dept = info['department']
        batch = info['batch']
        is_suspended = info['is_suspended']
        is_2fa = info['is_enrolled_in_2sv']
        is_admin = info['is_super_admin'] or info['is_delegated_admin']
        adm_resets = info.get('admin_resets', 0)
        slf_resets = info.get('self_resets', 0)
        tot_resets = info.get('total_password_resets', 0)
        storage_b = info['total_storage_bytes']

        if dept not in dept_map:
            dept_map[dept] = {
                'department': dept,
                'batch': batch,
                'total_assigned_seats': 0,
                'active_seats': 0,
                'dormant_seats': 0,
                'suspended_seats': 0,
                'two_factor_enforced_seats': 0,
                'admin_users_count': 0,
                'admin_resets': 0,
                'self_resets': 0,
                'total_password_resets': 0,
                'two_factor_coverage_pct': 0.0,
                'total_storage_bytes': 0
            }

        grp = dept_map[dept]
        grp['total_assigned_seats'] += 1
        if is_suspended:
            grp['suspended_seats'] += 1
        else:
            grp['active_seats'] += 1

        if is_2fa:
            grp['two_factor_enforced_seats'] += 1

        if is_admin:
            grp['admin_users_count'] += 1

        grp['admin_resets'] += adm_resets
        grp['self_resets'] += slf_resets
        grp['total_password_resets'] += tot_resets
        grp['total_storage_bytes'] += storage_b

    for grp in dept_map.values():
        tot_seats = max(1, grp['total_assigned_seats'])
        grp['two_factor_coverage_pct'] = round((grp['two_factor_enforced_seats'] / tot_seats) * 100.0, 2)

    governance_records = list(dept_map.values())

    if governance_records:
        with db_engine.begin() as conn:
            conn.execute(text('''
                              INSERT INTO department_governance
                              (department, batch, total_assigned_seats, active_seats, dormant_seats, suspended_seats,
                               two_factor_enforced_seats, admin_users_count, admin_resets, self_resets,
                               total_password_resets,
                               two_factor_coverage_pct, total_storage_bytes, updated_at)
                              VALUES (:department, :batch, :total_assigned_seats, :active_seats, :dormant_seats,
                                      :suspended_seats,
                                      :two_factor_enforced_seats, :admin_users_count, :admin_resets, :self_resets,
                                      :total_password_resets,
                                      :two_factor_coverage_pct, :total_storage_bytes,
                                      CURRENT_TIMESTAMP) ON CONFLICT (department) DO
                              UPDATE SET
                                  batch = EXCLUDED.batch,
                                  total_assigned_seats = EXCLUDED.total_assigned_seats,
                                  active_seats = EXCLUDED.active_seats,
                                  dormant_seats = EXCLUDED.dormant_seats,
                                  suspended_seats = EXCLUDED.suspended_seats,
                                  two_factor_enforced_seats = EXCLUDED.two_factor_enforced_seats,
                                  admin_users_count = EXCLUDED.admin_users_count,
                                  admin_resets = EXCLUDED.admin_resets,
                                  self_resets = EXCLUDED.self_resets,
                                  total_password_resets = EXCLUDED.total_password_resets,
                                  two_factor_coverage_pct = EXCLUDED.two_factor_coverage_pct,
                                  total_storage_bytes = EXCLUDED.total_storage_bytes,
                                  updated_at = CURRENT_TIMESTAMP;
                              '''), governance_records)

        print(f"    [+] Saved governance records for {len(governance_records)} departments.")

    return dept_map


def export_governance_report_csv(user_directory):
    """Exports full employee credential and governance audit to CSV file."""
    csv_filename = os.path.join(BASE_DIR, "cci_user_governance_report.csv")
    print(f"[*] Exporting comprehensive user governance report to CSV: {csv_filename}...")
    all_users_sorted = sorted(user_directory.values(), key=lambda x: (x['department'], -x['total_password_resets']))

    try:
        with open(csv_filename, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Department', 'Employee Name', 'Email', 'Privilege Tier',
                '2SV Enrolled', 'Is Suspended', 'Last Login Time',
                'IT Admin Forced Resets', 'User Self-Service Resets', 'Total Resets (180d)',
                'Last Reset Date', 'Risk Category', 'Enablement Recommendation'
            ])
            for u in all_users_sorted:
                writer.writerow([
                    u['department'], u['name'], u['email'], u['privilege_tier'],
                    'YES' if u['is_enrolled_in_2sv'] else 'NO',
                    'YES' if u['is_suspended'] else 'NO',
                    u['last_login_time'], u['admin_resets'], u['self_resets'],
                    u['total_password_resets'], u['last_password_reset_date'] or 'None',
                    u['password_risk_category'], u['password_recommendation']
                ])
        print(f"    [✓] CSV successfully generated with {len(all_users_sorted)} user rows.")
    except Exception as e:
        print(f"    [!] CSV Export Note: {e}")


def sync_mirrored_data(google_users, existing_storage_map, real_customer_id):
    print("\n" + "=" * 75)
    print(" [STAGE 2] INGESTING REAL STORAGE & RECONCILING GOVERNANCE POOL")
    print("=" * 75)

    creds = get_delegated_credentials()
    dir_service = build('admin', 'directory_v1', credentials=creds, cache_discovery=False)
    live_gmail_storage = probe_latest_user_storage_from_google(creds)
    now_dt = datetime.datetime.now(datetime.timezone.utc)

    # Ingest live licensing & capacity metrics
    assigned_license_emails, total_purchased_seats, dynamic_quota_gb, report_used_gb, report_date = sync_google_licensing_data(
        creds, google_users, real_customer_id
    )

    user_directory = {}
    realtime_drive_map = {}

    active_emails = [email for email, u in google_users.items() if not u.get('suspended', False)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_email = {
            executor.submit(fetch_realtime_user_storage, email): email
            for email in active_emails
        }
        for future in concurrent.futures.as_completed(future_to_email):
            email = future_to_email[future]
            realtime_drive_map[email] = future.result()

    total_domain_gmail_bytes = 0
    total_domain_drive_bytes = 0

    for email, u in google_users.items():
        name = u.get('name', {}).get('fullName', email)
        dept_name, batch_name = extract_user_department(u, existing_storage_map)
        is_2sv = bool(u.get('isEnrolledIn2Sv', False))
        is_suspended = bool(u.get('suspended', False))
        is_super = bool(u.get('isAdmin', False))
        is_delegated = bool(u.get('isDelegatedAdmin', False))
        last_login = u.get('lastLoginTime', '')

        if is_super:
            tier = 'Super Admin (Root)'
        elif is_delegated:
            tier = 'Delegated Admin'
        else:
            tier = 'Standard User'

        days_inact = None
        if last_login:
            try:
                ll_dt = datetime.datetime.fromisoformat(last_login.replace('Z', '+00:00'))
                days_inact = (now_dt - ll_dt).days
            except Exception:
                pass

        drive_b = realtime_drive_map.get(email, 0)
        if drive_b == 0 and email in existing_storage_map:
            drive_b = existing_storage_map[email].get('drive_bytes', 0)

        gmail_b = live_gmail_storage.get(email, 0)
        if gmail_b == 0 and email in existing_storage_map:
            gmail_b = existing_storage_map[email].get('gmail_bytes', 0)

        total_b = drive_b + gmail_b
        total_domain_drive_bytes += drive_b
        total_domain_gmail_bytes += gmail_b

        user_directory[email] = {
            'email': email,
            'name': name,
            'department': dept_name,
            'batch': batch_name,
            'is_enrolled_in_2sv': is_2sv,
            'is_suspended': is_suspended,
            'is_super_admin': is_super,
            'is_delegated_admin': is_delegated,
            'privilege_tier': tier,
            'last_login_time': last_login,
            'days_inactive': days_inact,
            'drive_bytes': drive_b,
            'gmail_bytes': gmail_b,
            'total_storage_bytes': total_b,
            'admin_resets': 0,
            'self_resets': 0,
            'total_password_resets': 0,
            'last_password_reset_date': None,
            'password_risk_category': '⚪ Stable (0 Resets)',
            'password_recommendation': 'None (Good Security Habits)',
            'external_shares_count': 0,
            'public_links_count': 0,
            'oauth_apps_count': 0,
            'critical_oauth_apps_count': 0,
            'has_forwarding': False,
            'forwarding_target': None,
            'cloud_maturity_tier': 'Needs Enablement',
            'license_waste_status': 'Optimal'
        }

    # Ingest Deep Security, Credential & DLP Telemetry from Google Workspace
    rep_service = build('admin', 'reports_v1', credentials=creds, cache_discovery=False)
    sync_governance_and_security_telemetry(rep_service, user_directory)
    sync_license_reclamation_pipeline(user_directory, assigned_license_emails)

    for u in user_directory.values():
        tot_r = u['total_password_resets']
        if tot_r >= 4:
            u['password_risk_category'] = '🔴 Chronic Resetter'
            u['password_recommendation'] = 'Enroll in Corporate Password Manager'
        elif tot_r >= 2:
            u['password_risk_category'] = '🟡 Frequent Resetter'
            u['password_recommendation'] = '1-on-1 Workspace Credential Coaching'
        elif tot_r == 1:
            u['password_risk_category'] = '🟢 Routine Rotation'
            u['password_recommendation'] = 'Normal (No Action Required)'
        else:
            u['password_risk_category'] = '⚪ Stable (0 Resets)'
            u['password_recommendation'] = 'None (Good Security Habits)'

    sorted_users = sorted(user_directory.values(), key=lambda x: x['total_storage_bytes'], reverse=True)

    with db_engine.begin() as conn:
        existing_db_emails = [r[0].lower() for r in
                              conn.execute(text("SELECT email FROM user_departments;")).fetchall()]
        stale = set(existing_db_emails) - set(user_directory.keys())
        if stale:
            print(f"    [-] Purging {len(stale)} deleted accounts from Supabase...")
            conn.execute(text("DELETE FROM user_departments WHERE LOWER(email) = ANY(:stale)"), {'stale': list(stale)})

        conn.execute(text('''
                          INSERT INTO user_departments
                          (email, name, department, batch, is_enrolled_in_2sv, is_suspended, is_super_admin,
                           is_delegated_admin, privilege_tier,
                           last_login_time, days_inactive, drive_bytes, gmail_bytes, total_storage_bytes,
                           admin_resets, self_resets, total_password_resets, last_password_reset_date,
                           password_risk_category, password_recommendation,
                           external_shares_count, public_links_count, oauth_apps_count, critical_oauth_apps_count,
                           has_forwarding, forwarding_target, cloud_maturity_tier, license_waste_status, updated_at)
                          VALUES (:email, :name, :department, :batch, :is_enrolled_in_2sv, :is_suspended,
                                  :is_super_admin, :is_delegated_admin, :privilege_tier,
                                  :last_login_time, :days_inactive, :drive_bytes, :gmail_bytes, :total_storage_bytes,
                                  :admin_resets, :self_resets, :total_password_resets, :last_password_reset_date,
                                  :password_risk_category, :password_recommendation,
                                  :external_shares_count, :public_links_count, :oauth_apps_count,
                                  :critical_oauth_apps_count,
                                  :has_forwarding, :forwarding_target, :cloud_maturity_tier, :license_waste_status,
                                  CURRENT_TIMESTAMP) ON CONFLICT (email) DO
                          UPDATE SET
                              name = EXCLUDED.name,
                              department = EXCLUDED.department,
                              batch = EXCLUDED.batch,
                              is_enrolled_in_2sv = EXCLUDED.is_enrolled_in_2sv,
                              is_suspended = EXCLUDED.is_suspended,
                              is_super_admin = EXCLUDED.is_super_admin,
                              is_delegated_admin = EXCLUDED.is_delegated_admin,
                              privilege_tier = EXCLUDED.privilege_tier,
                              last_login_time = EXCLUDED.last_login_time,
                              days_inactive = EXCLUDED.days_inactive,
                              drive_bytes = EXCLUDED.drive_bytes,
                              gmail_bytes = EXCLUDED.gmail_bytes,
                              total_storage_bytes = EXCLUDED.total_storage_bytes,
                              admin_resets = EXCLUDED.admin_resets,
                              self_resets = EXCLUDED.self_resets,
                              total_password_resets = EXCLUDED.total_password_resets,
                              last_password_reset_date = EXCLUDED.last_password_reset_date,
                              password_risk_category = EXCLUDED.password_risk_category,
                              password_recommendation = EXCLUDED.password_recommendation,
                              external_shares_count = EXCLUDED.external_shares_count,
                              public_links_count = EXCLUDED.public_links_count,
                              oauth_apps_count = EXCLUDED.oauth_apps_count,
                              critical_oauth_apps_count = EXCLUDED.critical_oauth_apps_count,
                              has_forwarding = EXCLUDED.has_forwarding,
                              forwarding_target = EXCLUDED.forwarding_target,
                              cloud_maturity_tier = EXCLUDED.cloud_maturity_tier,
                              license_waste_status = EXCLUDED.license_waste_status,
                              updated_at = CURRENT_TIMESTAMP;
                          '''), sorted_users)

    # Dynamic Governance Pool Reconciliation
    total_workspace_users = len(user_directory)
    total_assigned_paid = len(assigned_license_emails)
    available_buffer = max(0, total_purchased_seats - total_assigned_paid)

    print(f"    [+] 1. Total Purchased Seats:      {total_purchased_seats}")
    print(f"    [+] 2. Assigned Paid Seats:        {total_assigned_paid}")
    print(f"    [+] 3. Available Ready Seats:      {available_buffer}")
    print(f"    [+] 4. Total Workspace Accounts:   {total_workspace_users}")

    with db_engine.begin() as conn:
        conn.execute(text('''
                          INSERT INTO organization_governance_pool
                          (id, total_contract_licenses, assigned_licenses, total_workspace_users, available_accounts,
                           updated_at)
                          VALUES (1, :purchased, :assigned, :total_users, :available,
                                  CURRENT_TIMESTAMP) ON CONFLICT (id) DO
                          UPDATE SET
                              total_contract_licenses = EXCLUDED.total_contract_licenses,
                              assigned_licenses = EXCLUDED.assigned_licenses,
                              total_workspace_users = EXCLUDED.total_workspace_users,
                              available_accounts = EXCLUDED.available_accounts,
                              updated_at = CURRENT_TIMESTAMP;
                          '''), {
                         'purchased': total_purchased_seats,
                         'assigned': total_assigned_paid,
                         'total_users': total_workspace_users,
                         'available': available_buffer
                     })

    dept_governance_map = sync_department_governance_metrics(user_directory)
    sync_all_users_google_meet_recordings(user_directory, creds)
    sync_cross_department_matrix(creds, user_directory)
    export_governance_report_csv(user_directory)

    # Shared Drives Sync
    total_shared_drives_bytes = 0
    detailed_shared_drives = []
    batched_members = []

    try:
        drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
        drives_res = drive_service.drives().list(pageSize=100, useDomainAdminAccess=True).execute(num_retries=3)
        shared_drives = drives_res.get('drives', [])

        for d in shared_drives:
            if d.get('hidden', False) or d.get('organizerIsOnlyUser', False) == 'deleted':
                continue

            d_id = d.get('id')
            d_name = d.get('name')
            matched_dept, _ = match_department_and_batch(d_name)

            member_count = 0
            lead_name = 'Department Lead'
            try:
                perms_res = drive_service.permissions().list(
                    fileId=d_id, supportsAllDrives=True, useDomainAdminAccess=True,
                    fields="permissions(id,displayName,emailAddress,role)"
                ).execute(num_retries=3)
                perms = perms_res.get('permissions', [])
                member_count = len(perms)
                for p in perms:
                    p_email = p.get('emailAddress')
                    p_name = p.get('displayName') or p_email or 'Workspace Member'
                    p_role = p.get('role', 'Member').capitalize()
                    if 'organizer' in p.get('role', '').lower():
                        lead_name = p_name
                    if p_email:
                        batched_members.append({
                            'sid': d_id,
                            'name': p_name,
                            'email': p_email,
                            'role': p_role,
                            'dept': matched_dept
                        })
            except Exception:
                pass

            drive_bytes = 0
            page_tok = None
            try:
                while True:
                    f_res = drive_service.files().list(
                        corpora='drive', driveId=d_id, includeItemsFromAllDrives=True,
                        supportsAllDrives=True, fields='nextPageToken, files(quotaBytesUsed, size)',
                        pageSize=1000, pageToken=page_tok
                    ).execute(num_retries=3)
                    for f in f_res.get('files', []):
                        drive_bytes += int(f.get('quotaBytesUsed') or f.get('size') or 0)
                    page_tok = f_res.get('nextPageToken')
                    if not page_tok:
                        break
            except Exception:
                pass

            total_shared_drives_bytes += drive_bytes
            detailed_shared_drives.append({
                'sid': d_id,
                'name': d_name,
                'dept': matched_dept,
                'lead': lead_name,
                'sbytes': drive_bytes,
                'm_count': member_count,
                'desc': 'Google Workspace Team Shared Drive'
            })

        detailed_shared_drives.sort(key=lambda x: x['sbytes'], reverse=True)

        with db_engine.begin() as conn:
            if detailed_shared_drives:
                conn.execute(text('''
                                  INSERT INTO shared_spaces (space_id, name, department, space_type, owner_lead,
                                                             storage_bytes, member_count, description, updated_at)
                                  VALUES (:sid, :name, :dept, 'Shared Drive', :lead, :sbytes, :m_count, :desc,
                                          CURRENT_TIMESTAMP) ON CONFLICT (space_id) DO
                                  UPDATE SET
                                      name = EXCLUDED.name,
                                      department = EXCLUDED.department,
                                      owner_lead = EXCLUDED.owner_lead,
                                      storage_bytes = EXCLUDED.storage_bytes,
                                      member_count = EXCLUDED.member_count,
                                      updated_at = CURRENT_TIMESTAMP;
                                  '''), detailed_shared_drives)

            if batched_members:
                conn.execute(text('''
                                  INSERT INTO space_members (space_id, name, email, role, department)
                                  VALUES (:sid, :name, :email, :role, :dept) ON CONFLICT (space_id, email) DO
                                  UPDATE SET
                                      name = EXCLUDED.name,
                                      role = EXCLUDED.role,
                                      department = EXCLUDED.department;
                                  '''), batched_members)
    except Exception as e:
        print(f"    [Drive API Note]: {e}")

    # Org Storage Snapshot
    today = datetime.date.today()
    itemized_sum_gb = round(
        (total_domain_gmail_bytes + total_domain_drive_bytes + total_shared_drives_bytes) / (1024 ** 3), 2)
    final_used_gb = report_used_gb if report_used_gb > 0 else itemized_sum_gb
    final_quota_gb = dynamic_quota_gb if dynamic_quota_gb > 0 else ORGANIZATION_STORAGE_QUOTA_GB
    unattributed_system_gb = max(round(final_used_gb - itemized_sum_gb, 2), 0.0)
    valid_snapshot_date = report_date or (today - datetime.timedelta(days=LAG_BUFFER_DAYS)).isoformat()

    with db_engine.begin() as conn:
        conn.execute(text('''
                          INSERT INTO org_storage_snapshots
                          (snapshot_date, total_quota_gb, used_storage_gb, personal_drives_gb, gmail_gb,
                           shared_drives_gb, unattributed_system_gb, updated_at)
                          VALUES (:sdate, :total_gb, :used_gb, :drive_gb, :gmail_gb, :shared_gb, :unattributed_gb,
                                  CURRENT_TIMESTAMP) ON CONFLICT (snapshot_date) DO
                          UPDATE SET
                              total_quota_gb = EXCLUDED.total_quota_gb,
                              used_storage_gb = EXCLUDED.used_storage_gb,
                              personal_drives_gb = EXCLUDED.personal_drives_gb,
                              gmail_gb = EXCLUDED.gmail_gb,
                              shared_drives_gb = EXCLUDED.shared_drives_gb,
                              unattributed_system_gb = EXCLUDED.unattributed_system_gb,
                              updated_at = CURRENT_TIMESTAMP;
                          '''), {
                         'sdate': valid_snapshot_date,
                         'total_gb': final_quota_gb,
                         'used_gb': final_used_gb,
                         'drive_gb': round(total_domain_drive_bytes / (1024 ** 3), 2),
                         'gmail_gb': round(total_domain_gmail_bytes / (1024 ** 3), 2),
                         'shared_gb': round(total_shared_drives_bytes / (1024 ** 3), 2),
                         'unattributed_gb': unattributed_system_gb
                     })

    # =========================================================================
    # DYNAMIC BACKFILL FROM DOMAIN INCEPTION TO TODAY (NO DUPLICATES)
    # =========================================================================
    domain_start_date = get_domain_inception_date(dir_service)
    end_date = today - datetime.timedelta(days=LAG_BUFFER_DAYS)
    total_days_span = max(0, (end_date - domain_start_date).days)

    print(
        f"[*] Total domain history span: {total_days_span} days ({domain_start_date.isoformat()} to {end_date.isoformat()}).")

    all_domain_days = [
        (domain_start_date + datetime.timedelta(days=i)).isoformat()
        for i in range(total_days_span + 1)
    ]

    with db_engine.connect() as conn:
        existing_dates = set(r[0] for r in conn.execute(
            text("SELECT DISTINCT date FROM daily_metrics;")
        ).fetchall())

    days = [d for d in all_domain_days if d not in existing_dates]
    days.sort()

    print(f"[*] Already saved in Supabase: {len(existing_dates)} days (Skipping).")
    print(f"[*] Missing dates to sync:    {len(days)} days.")

    usage_params = (
        'drive:num_google_documents_created,'
        'drive:num_google_spreadsheets_created,'
        'drive:num_google_forms_created,'
        'drive:num_google_presentations_created,'
        'gmail:num_emails_sent'
    )

    all_records = []
    user_totals = defaultdict(lambda: {'docs': 0, 'emails': 0})

    for d_str in days:
        user_map = {}
        for email, info in user_directory.items():
            user_map[email] = {
                'date': d_str, 'email': email, 'name': info['name'],
                'department': info['department'], 'batch': info['batch'],
                'docs': 0, 'sheets': 0, 'forms': 0, 'slides': 0,
                'calendar_events': 0, 'meet_calls': 0, 'meet_minutes': 0,
                'meet_created_calls': 0, 'meet_created_minutes': 0,
                'meet_joined_calls': 0, 'meet_joined_minutes': 0,
                'emails': 0,
                'drive_bytes': info['drive_bytes'],
                'gmail_bytes': info['gmail_bytes'],
                'estimated_minutes': 0
            }

        try:
            usage = rep_service.userUsageReport().get(
                userKey='all', date=d_str, parameters=usage_params
            ).execute(num_retries=2)
            for report in usage.get('usageReports', []):
                em = report.get('entity', {}).get('userEmail', '').lower()
                if em in user_map:
                    pms = {p['name']: p for p in report.get('parameters', [])}
                    d_cnt = int(pms.get('drive:num_google_documents_created', {}).get('intValue', 0))
                    s_cnt = int(pms.get('drive:num_google_spreadsheets_created', {}).get('intValue', 0))
                    f_cnt = int(pms.get('drive:num_google_forms_created', {}).get('intValue', 0))
                    sl_cnt = int(pms.get('drive:num_google_presentations_created', {}).get('intValue', 0))
                    e_cnt = int(pms.get('gmail:num_emails_sent', {}).get('intValue', 0))

                    user_map[em]['docs'] = d_cnt
                    user_map[em]['sheets'] = s_cnt
                    user_map[em]['forms'] = f_cnt
                    user_map[em]['slides'] = sl_cnt
                    user_map[em]['emails'] = e_cnt

                    user_totals[em]['docs'] += (d_cnt + s_cnt + f_cnt + sl_cnt)
                    user_totals[em]['emails'] += e_cnt
        except HttpError as err:
            if err.resp.status in [400, 404]:
                pass  # Date is beyond Google's audit retention period
            else:
                print(f"    [!] Reports error for {d_str}: {err}")
        except Exception:
            pass

        try:
            start_time = f"{d_str}T00:00:00Z"
            end_time = f"{d_str}T23:59:59Z"

            cals = rep_service.activities().list(
                userKey='all', applicationName='calendar', startTime=start_time, endTime=end_time
            ).execute(num_retries=2)
            for act in cals.get('items', []):
                actor = act.get('actor', {}).get('email', '').lower()
                if actor in user_map:
                    user_map[actor]['calendar_events'] += 1

            meets = rep_service.activities().list(
                userKey='all', applicationName='meet', startTime=start_time, endTime=end_time
            ).execute(num_retries=2)
            for act in meets.get('items', []):
                actor = act.get('actor', {}).get('email', '').lower()
                if actor in user_map:
                    for ev in act.get('events', []):
                        pms = {p['name']: p for p in ev.get('parameters', [])}
                        dur = int(pms.get('duration_seconds', {}).get('intValue', 0)) // 60
                        is_org = pms.get('is_organizer', {}).get('boolValue', False)
                        user_map[actor]['meet_calls'] += 1
                        user_map[actor]['meet_minutes'] += dur
                        if is_org:
                            user_map[actor]['meet_created_calls'] += 1
                            user_map[actor]['meet_created_minutes'] += dur
                        else:
                            user_map[actor]['meet_joined_calls'] += 1
                            user_map[actor]['meet_joined_minutes'] += dur
        except HttpError as err:
            if err.resp.status in [400, 404]:
                pass
        except Exception:
            pass

        for m in user_map.values():
            m['estimated_minutes'] = (
                    (m['docs'] * 15) + (m['sheets'] * 20) + (m['forms'] * 10) +
                    (m['slides'] * 25) + (m['calendar_events'] * 5) + (m['emails'] * 3) + m['meet_minutes']
            )

        all_records.extend(list(user_map.values()))

    # Update Cloud Maturity Tiers
    with db_engine.begin() as conn:
        for em, t_vals in user_totals.items():
            if t_vals['docs'] >= 3:
                c_tier = 'Cloud Champion'
            elif t_vals['docs'] >= 1:
                c_tier = 'Cloud Practitioner'
            elif t_vals['emails'] > 0:
                c_tier = 'Legacy Emailer'
            else:
                c_tier = 'Needs Enablement'

            conn.execute(text('''
                              UPDATE user_departments
                              SET cloud_maturity_tier = :tier
                              WHERE LOWER(email) = :email;
                              '''), {'tier': c_tier, 'email': em})

    if all_records:
        query = text('''
                     INSERT INTO daily_metrics
                     (date, email, name, department, batch, docs, sheets, forms, slides, calendar_events,
                      meet_calls, meet_minutes, meet_created_calls, meet_created_minutes,
                      meet_joined_calls, meet_joined_minutes, emails, drive_bytes, gmail_bytes, estimated_minutes)
                     VALUES (:date, :email, :name, :department, :batch, :docs, :sheets, :forms, :slides,
                             :calendar_events, :meet_calls, :meet_minutes, :meet_created_calls, :meet_created_minutes,
                             :meet_joined_calls, :meet_joined_minutes, :emails, :drive_bytes, :gmail_bytes,
                             :estimated_minutes) ON CONFLICT (date, email) DO
                     UPDATE SET
                         name = EXCLUDED.name, department = EXCLUDED.department, batch = EXCLUDED.batch,
                         docs = EXCLUDED.docs, sheets = EXCLUDED.sheets, forms = EXCLUDED.forms, slides = EXCLUDED.slides,
                         calendar_events = EXCLUDED.calendar_events, meet_calls = EXCLUDED.meet_calls, meet_minutes = EXCLUDED.meet_minutes,
                         meet_created_calls = EXCLUDED.meet_created_calls, meet_created_minutes = EXCLUDED.meet_created_minutes,
                         meet_joined_calls = EXCLUDED.meet_joined_calls, meet_joined_minutes = EXCLUDED.meet_joined_minutes,
                         emails = EXCLUDED.emails, drive_bytes = EXCLUDED.drive_bytes, gmail_bytes = EXCLUDED.gmail_bytes,
                         estimated_minutes = EXCLUDED.estimated_minutes;
                     ''')
        chunk_size = 500
        with db_engine.begin() as conn:
            for i in range(0, len(all_records), chunk_size):
                conn.execute(query, all_records[i:i + chunk_size])

    with db_engine.begin() as conn:
        sync_dynamic_department_framework(conn)

    return user_directory, dept_governance_map


def sync_dynamic_department_framework(conn):
    discovered = conn.execute(text('''
                                   SELECT DISTINCT department
                                   FROM (SELECT department
                                         FROM user_departments
                                         WHERE department IS NOT NULL
                                           AND department NOT LIKE '%Unassigned%'
                                         UNION
                                         SELECT department
                                         FROM daily_metrics
                                         WHERE department IS NOT NULL
                                           AND department NOT LIKE '%Unassigned%') depts;
                                   ''')).fetchall()

    for row in discovered:
        dept = row[0].strip()
        if not dept:
            continue

        lead_row = conn.execute(text('''
                                     SELECT COALESCE(u.name, d.name, d.email) as lead_name
                                     FROM daily_metrics d
                                              LEFT JOIN user_departments u ON LOWER(u.email) = LOWER(d.email)
                                     WHERE d.department = :dept
                                     GROUP BY COALESCE(u.name, d.name, d.email)
                                     ORDER BY (SUM(d.docs + d.sheets + d.forms + d.slides) + SUM(d.emails))
                                         DESC LIMIT 1;
                                     '''), {'dept': dept}).fetchone()

        lead_name = lead_row[0] if lead_row else 'Department Lead'

        if dept in ['IT Department', 'Information Technology']:
            batch, focus, target = 'IT', 'Advanced Workspace Administration', '4,000+ pts'
        elif dept in ['Management', 'Executive']:
            batch, focus, target = 'Executive', 'Executive Governance', '5,000+ pts'
        elif dept in ['Finance', 'Accounting', 'Credit and Collection', 'CNC & Treasury', 'Purchasing', 'Sales',
                      'Service']:
            batch, focus, target = 'Batch 1', 'Business Operations', '3,500+ pts'
        elif dept in ['Production', 'Warehouse', 'HR', 'Human Resources', 'Audit']:
            batch, focus, target = 'Batch 2', 'Operations & Compliance', '3,000+ pts'
        else:
            batch, focus, target = 'Batch 3', 'Specialized Operations', '2,500+ pts'

        conn.execute(text('''
                          INSERT INTO department_framework (department, batch, focus, lead_name, target_pts, workflow,
                                                            shared_drive, updated_at)
                          VALUES (:dept, :batch, :focus, :lead, :target, :wf, :sd,
                                  CURRENT_TIMESTAMP) ON CONFLICT (department) DO
                          UPDATE SET
                              lead_name = CASE WHEN EXCLUDED.lead_name != 'Department Lead' THEN EXCLUDED.lead_name ELSE department_framework.lead_name END,
                              batch = EXCLUDED.batch, focus = EXCLUDED.focus, updated_at = CURRENT_TIMESTAMP;
                          '''), {
                         'dept': dept, 'batch': batch, 'focus': focus, 'lead': lead_name,
                         'target': target, 'wf': f"Operational documentation and cloud workflows for {dept}.",
                         'sd': f"{dept} Central Drive"
                     })


def backfill_all_historical_drive_files(user_directory):
    """
    Pulls ALL historical Drive files created by domain users from inception to today.
    Groups creations by (date, email) and merges them into daily_metrics.
    Skips processing if the data is already recorded.
    """
    print("\n" + "=" * 75)
    print(" [*] RUNNING LIFETIME HISTORICAL DRIVE ASSET BACKFILL (NO TIME LIMIT)")
    print("=" * 75)

    creds = get_delegated_credentials()
    drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)

    historical_tallies = defaultdict(lambda: {'docs': 0, 'sheets': 0, 'slides': 0, 'forms': 0})
    page_token = None
    batch_page = 1

    print("[*] Traversing all corporate drive assets across all years in 1,000-item chunks...")
    try:
        while True:
            res = drive_service.files().list(
                q="trashed = false",
                corpora='allDrives',
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                fields="nextPageToken, files(id, mimeType, createdTime, owners)",
                pageSize=1000,
                pageToken=page_token
            ).execute(num_retries=3)

            files = res.get('files', [])
            for f in files:
                created_time = f.get('createdTime')
                if not created_time:
                    continue

                date_str = created_time[:10]  # Extracts YYYY-MM-DD
                mime = f.get('mimeType', '')
                owners = f.get('owners', [])
                owner_email = owners[0].get('emailAddress', '').lower() if owners else ''

                if not owner_email or ALLOWED_DOMAIN not in owner_email:
                    continue

                if 'document' in mime:
                    historical_tallies[(date_str, owner_email)]['docs'] += 1
                elif 'spreadsheet' in mime:
                    historical_tallies[(date_str, owner_email)]['sheets'] += 1
                elif 'presentation' in mime:
                    historical_tallies[(date_str, owner_email)]['slides'] += 1
                elif 'form' in mime:
                    historical_tallies[(date_str, owner_email)]['forms'] += 1

            print(f"    --> Processed Batch {batch_page} (1,000 files examined)...")
            batch_page += 1
            page_token = res.get('nextPageToken')
            if not page_token:
                break

    except Exception as e:
        print(f"    [!] Drive backfill note: {e}")

    records = []
    for (d_str, email), counts in historical_tallies.items():
        u_info = user_directory.get(email, {'name': email, 'department': 'Operations', 'batch': 'General'})
        records.append({
            'date': d_str,
            'email': email,
            'name': u_info.get('name', email),
            'department': u_info.get('department', 'Operations'),
            'batch': u_info.get('batch', 'General'),
            'docs': counts['docs'],
            'sheets': counts['sheets'],
            'forms': counts['forms'],
            'slides': counts['slides'],
            'calendar_events': 0,
            'meet_calls': 0,
            'meet_minutes': 0,
            'meet_created_calls': 0,
            'meet_created_minutes': 0,
            'meet_joined_calls': 0,
            'meet_joined_minutes': 0,
            'emails': 0,
            'drive_bytes': 0,
            'gmail_bytes': 0,
            'estimated_minutes': (counts['docs'] * 15) + (counts['sheets'] * 20) + (counts['forms'] * 10) + (
                        counts['slides'] * 25)
        })

    if records:
        print(f"[*] Committing {len(records)} historical date/user records to Supabase...")
        insert_query = text('''
                            INSERT INTO daily_metrics
                            (date, email, name, department, batch, docs, sheets, forms, slides, calendar_events,
                             meet_calls, meet_minutes, meet_created_calls, meet_created_minutes,
                             meet_joined_calls, meet_joined_minutes, emails, drive_bytes, gmail_bytes,
                             estimated_minutes)
                            VALUES (:date, :email, :name, :department, :batch, :docs, :sheets, :forms, :slides,
                                    :calendar_events, :meet_calls, :meet_minutes, :meet_created_calls,
                                    :meet_created_minutes,
                                    :meet_joined_calls, :meet_joined_minutes, :emails, :drive_bytes, :gmail_bytes,
                                    :estimated_minutes) ON CONFLICT (date, email) DO
                            UPDATE SET
                                docs = GREATEST(daily_metrics.docs, EXCLUDED.docs),
                                sheets = GREATEST(daily_metrics.sheets, EXCLUDED.sheets),
                                forms = GREATEST(daily_metrics.forms, EXCLUDED.forms),
                                slides = GREATEST(daily_metrics.slides, EXCLUDED.slides);
                            ''')
        chunk_size = 500
        with db_engine.begin() as conn:
            for i in range(0, len(records), chunk_size):
                conn.execute(insert_query, records[i:i + chunk_size])
        print("    [✓] Lifetime Drive History successfully synchronized without overwriting existing metrics.")


def postflight_parity_check(google_users, user_directory, dept_governance_map):
    print("\n" + "=" * 105)
    print(" [STAGE 3] POST-FLIGHT PARITY, CREDENTIAL AUDIT & GOVERNANCE REPORT")
    print("=" * 105)

    with db_engine.connect() as conn:
        u_count = conn.execute(text("SELECT COUNT(DISTINCT email) FROM user_departments;")).fetchone()[0]
        d_count = conn.execute(text("SELECT COUNT(*) FROM daily_metrics;")).fetchone()[0]
        shared_drives = \
        conn.execute(text("SELECT COUNT(*) FROM shared_spaces WHERE space_type = 'Shared Drive';")).fetchone()[0]
        dept_gov_count = conn.execute(text("SELECT COUNT(*) FROM department_governance;")).fetchone()[0]
        gov_pool = conn.execute(text("""
                                     SELECT total_contract_licenses,
                                            assigned_licenses,
                                            total_workspace_users,
                                            available_accounts
                                     FROM organization_governance_pool
                                     WHERE id = 1;
                                     """)).fetchone()
        total_gmail = conn.execute(text("SELECT COALESCE(SUM(gmail_bytes), 0) FROM user_departments;")).fetchone()[0]
        total_drive = conn.execute(text("SELECT COALESCE(SUM(drive_bytes), 0) FROM user_departments;")).fetchone()[0]
        total_shared_b = conn.execute(text(
            "SELECT COALESCE(SUM(storage_bytes), 0) FROM shared_spaces WHERE space_type = 'Shared Drive';")).fetchone()[
            0]
        snapshot_row = conn.execute(text(
            "SELECT total_quota_gb, used_storage_gb, unattributed_system_gb FROM org_storage_snapshots ORDER BY snapshot_date DESC LIMIT 1;")).fetchone()
        meet_vids_count = conn.execute(text("SELECT COUNT(*) FROM meet_recordings;")).fetchone()[0]
        meet_vids_b = conn.execute(text("SELECT COALESCE(SUM(size_bytes), 0) FROM meet_recordings;")).fetchone()[0]

        pwd_resets_count = conn.execute(text("SELECT COUNT(*) FROM password_reset_events;")).fetchone()[0]
        dlp_count = conn.execute(text("SELECT COUNT(*) FROM dlp_file_exposures;")).fetchone()[0]
        oauth_count = conn.execute(text("SELECT COUNT(*) FROM oauth_app_authorizations;")).fetchone()[0]
        fwd_count = conn.execute(text("SELECT COUNT(*) FROM mailbox_forwarding_rules;")).fetchone()[0]
        reclaim_seats = conn.execute(text("""
                                          SELECT COUNT(*),
                                                 COALESCE(SUM(prorated_recovery_php), 0),
                                                 COALESCE(SUM(annual_cost_php), 0)
                                          FROM license_reclamation_pipeline;
                                          """)).fetchone()

    quota_tb = float(snapshot_row[0] or ORGANIZATION_STORAGE_QUOTA_GB) / 1000.0 if snapshot_row else (
                ORGANIZATION_STORAGE_QUOTA_GB / 1000.0)
    used_gb = float(snapshot_row[1]) if snapshot_row and snapshot_row[1] else (
                                                                                          total_gmail + total_drive + total_shared_b) / (
                                                                                          1024 ** 3)
    unattributed_gb = float(snapshot_row[2]) if snapshot_row and snapshot_row[2] else 0.0

    print(f" Live Google Directory Users: {len(google_users)}")
    print(f" Supabase Mirrored Users:     {u_count}")
    print(f" Total Telemetry Rows:        {d_count:,}")
    print(f" Department Governance Rows:  {dept_gov_count}")
    if gov_pool:
        print(
            f" Governance License Pool:     {gov_pool[0]} Purchased | {gov_pool[1]} Assigned | {gov_pool[3]} Ready Buffer | ({gov_pool[2]} Accounts in Directory)")
    print(f" Active Team Shared Drives:   {shared_drives} ({total_shared_b / (1024 ** 3):.2f} GB)")
    print(f" Saved Meeting Recordings:    {meet_vids_count} ({meet_vids_b / (1024 ** 3):.2f} GB across all users)")
    print(f" Total Gmail Storage:         {total_gmail / (1024 ** 3):.2f} GB")
    print(f" Total Personal Drive:        {total_drive / (1024 ** 3):.2f} GB")
    print(f" System Overheads / Vault:    {unattributed_gb:.2f} GB")
    print("-" * 105)
    print(f" [✓] GOOGLE ADMIN MATCH:       {used_gb:.2f} GB of shared {quota_tb:.0f} TB used")
    print("=" * 105)

    # EXECUTIVE GOVERNANCE & CREDENTIAL KPI SUMMARY
    total_users_cnt = len(user_directory)
    unique_resetters = [u for u in user_directory.values() if u['total_password_resets'] > 0]
    total_admin_resets = sum(u['admin_resets'] for u in user_directory.values())
    total_self_resets = sum(u['self_resets'] for u in user_directory.values())
    chronic_resetters = [u for u in user_directory.values() if u['total_password_resets'] >= 3]
    total_admins = [u for u in user_directory.values() if u['is_super_admin'] or u['is_delegated_admin']]

    print("\n" + "=" * 105)
    print(" SECTION 1: EXECUTIVE GOVERNANCE & CREDENTIAL KPI SUMMARY")
    print("=" * 105)
    print(f" • Total Active/Suspended Accounts:       {total_users_cnt}")
    print(
        f" • Unique Users Who Reset Passwords:      {len(unique_resetters)} ({round(len(unique_resetters) / max(1, total_users_cnt) * 100, 1)}% of domain)")
    print(f" • Total Password Reset Events:           {pwd_resets_count} in 180 days")
    print(f"   ├─ IT Admin Forced Resets (Ticket Cost): {total_admin_resets}")
    print(f"   └─ User Self-Service / Recoveries:       {total_self_resets}")
    print(f" • Chronic Resetters (3+ times):          {len(chronic_resetters)} accounts")
    print(f" • Privileged Administrators:             {len(total_admins)} accounts")
    print(f" • DLP External File Leaks:               {dlp_count} external/public exposures captured")
    print(f" • Shadow IT OAuth Grants:                {oauth_count} third-party apps tracked")
    print(f" • Mailbox Forwarding Rules:              {fwd_count} active routing rules logged")
    print(
        f" • License Reclaim Pipeline:              {reclaim_seats[0]} seats (₱{float(reclaim_seats[1]):,.2f} pro-rated | ₱{float(reclaim_seats[2]):,.2f}/yr total)")

    # DEPARTMENTAL DISRUPTION & PRIVILEGE MATRIX
    print("\n" + "=" * 105)
    print(" SECTION 2: DEPARTMENTAL DISRUPTION & PRIVILEGE MATRIX")
    print("=" * 105)
    print(
        f" {'DEPARTMENT':<24} | {'USERS':>6} | {'2SV %':>7} | {'ADMINS':>7} | {'IT RESETS':>10} | {'SELF RESETS':>12} | {'TOTAL RESETS':>12}")
    print("-" * 105)

    sorted_depts = sorted(dept_governance_map.items(),
                          key=lambda x: (x[1]['total_password_resets'], x[1]['total_assigned_seats']), reverse=True)
    for dept_name, s in sorted_depts:
        print(
            f" {dept_name:<24} | {s['total_assigned_seats']:>6} | {s['two_factor_coverage_pct']:>6.1f}% | {s['admin_users_count']:>7} | {s['admin_resets']:>10} | {s['self_resets']:>12} | {s['total_password_resets']:>12}")

    print("=" * 105 + "\n")


def execute_full_pipeline():
    init_database_tables()
    google_users, existing_storage_map, real_customer_id = preflight_reconciliation_check()
    user_directory, dept_governance_map = sync_mirrored_data(google_users, existing_storage_map, real_customer_id)
    backfill_all_historical_drive_files(user_directory)
    postflight_parity_check(google_users, user_directory, dept_governance_map)


if __name__ == '__main__':
    execute_full_pipeline()