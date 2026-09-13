"""
Coolaire Consolidated Inc. (CCI) - Comprehensive Cross-Department Collaboration Probe
Multi-Channel Detection:
1. Persistent Collaboration: Shared Drive Cross-Department Membership
2. Active Collaboration: File Edits, Views & Access Sharing across Departments
3. Calendar Collaboration: Cross-Department Meeting Invites & Sessions
Does NOT write to or modify any database tables.
"""

import os
import sys
import datetime
import re
from collections import defaultdict
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.environ.get('SERVICE_ACCOUNT_FILE', os.path.join(BASE_DIR, 'old/credentials-old.json'))
ADMIN_EMAIL = os.environ.get('WORKSPACE_ADMIN_EMAIL', 'jarick.montojo@coolaireconsolidated.com')
ALLOWED_DOMAIN = os.environ.get('ALLOWED_DOMAIN', 'coolaireconsolidated.com')

SCOPES = [
    'https://www.googleapis.com/auth/admin.directory.user.readonly',
    'https://www.googleapis.com/auth/admin.reports.audit.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

DEPARTMENT_TAXONOMY = {
    'Finance': ['finance', 'fa', 'billing', 'disbursement', 'ap', 'ar', 'financial'],
    'Accounting': ['accounting', 'acct', 'bookkeeper', 'audit_acct', 'general_accounting', 'ledger'],
    'CNC & Treasury': ['cnc', 'treasury', 'cash', 'treasurer'],
    'Credit and Collection': ['credit and collection', 'credit & collection', 'collection', 'credit', 'collections', 'collector'],
    'Purchasing': ['purchasing', 'procurement', 'purch', 'buyer', 'sourcing'],
    'Sales': ['sales', 'commercial', 'account executive', 'business development', 'bdr'],
    'Service': ['service', 'technical_service', 'technician', 'maintenance', 'hvac', 'aftersales'],
    'Production': ['production', 'manufacturing', 'plant', 'factory', 'assembly', 'fabrication'],
    'Warehouse': ['warehouse', 'logistics', 'inventory', 'stock', 'receiving', 'storekeeper', 'warehousing'],
    'HR': ['hr', 'human resources', 'human_resources', 'people', 'personnel', 'admin_hr'],
    'Audit': ['audit', 'internal_audit', 'compliance', 'qa_audit'],
    'Asset': ['asset', 'facilities', 'fleet', 'machinery', 'property'],
    'Marketing': ['marketing', 'mktg', 'creatives', 'branding', 'graphics', 'digital', 'media'],
    'Imports': ['imports', 'customs', 'shipping', 'brokerage', 'importation', 'forwarding'],
    'IT Department': ['it', 'tech', 'sysadmin', 'information technology', 'systems', 'edp', 'developer'],
    'Management': ['management', 'executive', 'c-level', 'board', 'director', 'president', 'ceo', 'coo']
}

def match_department(raw_text, email=""):
    clean_email = (email or '').lower().strip()
    if any(k in clean_email for k in ['it@', 'tech@', 'sysadmin@']) or clean_email == ADMIN_EMAIL.lower():
        return 'IT Department'
    if any(k in clean_email for k in ['ceo@', 'president@', 'board@', 'exec@', 'admin@']):
        return 'Management'

    if not raw_text:
        return 'Operations (Unassigned)'

    raw_clean = raw_text.lower().replace('&', 'and').replace('/', ' ')
    raw_clean = re.sub(r'[^a-z0-9\s]', ' ', raw_clean).strip()
    words = raw_clean.split()

    if 'credit and collection' in raw_clean or 'collection' in words or 'credit' in words:
        return 'Credit and Collection'
    if 'warehouse' in raw_clean or 'logistics' in words or 'inventory' in words:
        return 'Warehouse'
    if 'marketing' in raw_clean or 'mktg' in words:
        return 'Marketing'
    if 'accounting' in raw_clean or 'acct' in words:
        return 'Accounting'
    if 'finance' in raw_clean or 'fa' in words:
        return 'Finance'

    for canonical_name, aliases in DEPARTMENT_TAXONOMY.items():
        if canonical_name.lower() in raw_clean:
            return canonical_name
        for alias in aliases:
            if alias in raw_clean or alias in words:
                return canonical_name

    return raw_text.strip()


def build_user_directory(creds):
    """Fetches users from Supabase or Google Directory API."""
    user_map = {}
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        try:
            from sqlalchemy import create_engine, text
            engine = create_engine(db_url)
            with engine.connect() as conn:
                rows = conn.execute(text("SELECT email, name, department FROM user_departments;")).fetchall()
                for r in rows:
                    user_map[r[0].lower().strip()] = {
                        'name': r[1] or r[0],
                        'department': r[2] or 'Operations (Unassigned)'
                    }
            if user_map:
                print(f"[+] Loaded {len(user_map)} accounts from Supabase.")
                return user_map
        except Exception:
            pass

    dir_service = build('admin', 'directory_v1', credentials=creds, cache_discovery=False)
    page_token = None
    while True:
        res = dir_service.users().list(customer='my_customer', maxResults=500, pageToken=page_token).execute()
        for u in res.get('users', []):
            em = u.get('primaryEmail', '').lower().strip()
            name = u.get('name', {}).get('fullName', em)
            raw_dept = None
            for org in u.get('organizations', []):
                raw_dept = org.get('department') or org.get('title')
                if raw_dept:
                    break
            user_map[em] = {'name': name, 'department': match_department(raw_dept, em)}

        page_token = res.get('nextPageToken')
        if not page_token:
            break

    print(f"[+] Loaded {len(user_map)} accounts from Google Directory API.")
    return user_map


def probe_collaboration():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"[!] Key file not found: {SERVICE_ACCOUNT_FILE}")
        sys.exit(1)

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    ).with_subject(ADMIN_EMAIL)

    print("=" * 80)
    print(" COOLAIRE CONSOLIDATED INC. - MULTI-CHANNEL COLLABORATION AUDIT")
    print(f" Domain: {ALLOWED_DOMAIN} | Admin: {ADMIN_EMAIL}")
    print("=" * 80 + "\n")

    user_directory = build_user_directory(creds)
    reports_service = build('admin', 'reports_v1', credentials=creds, cache_discovery=False)
    drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)

    cross_dept_matrix = defaultdict(int)
    employee_pairs = defaultdict(int)
    discovered_proofs = []

    # -------------------------------------------------------------------------
    # CHANNEL 1: SHARED DRIVE CROSS-MEMBERSHIP (Permanent Collaboration)
    # -------------------------------------------------------------------------
    print("\n[*] Channel 1: Auditing Team Shared Drive Cross-Department Memberships...")
    try:
        drives_res = drive_service.drives().list(pageSize=100, useDomainAdminAccess=True).execute()
        drives = drives_res.get('drives', [])
        print(f"    -> Discovered {len(drives)} enterprise Shared Drives.")

        for d in drives:
            d_id = d.get('id')
            d_name = d.get('name')
            drive_dept = match_department(d_name)

            if 'Unassigned' in drive_dept:
                continue

            # Fetch members of this drive
            perms_res = drive_service.permissions().list(
                fileId=d_id, supportsAllDrives=True, useDomainAdminAccess=True,
                fields="permissions(displayName,emailAddress,role)"
            ).execute()

            for p in perms_res.get('permissions', []):
                mem_email = (p.get('emailAddress') or '').lower().strip()
                if not mem_email or ALLOWED_DOMAIN not in mem_email:
                    continue

                mem_info = user_directory.get(mem_email, {'name': p.get('displayName') or mem_email, 'department': 'Operations (Unassigned)'})
                mem_dept = mem_info['department']
                role = p.get('role', 'member').capitalize()

                if mem_dept != drive_dept and 'Unassigned' not in mem_dept:
                    cross_dept_matrix[(mem_dept, drive_dept)] += 1
                    employee_pairs[(mem_email, f"Team Drive ({d_name})", mem_dept, drive_dept)] += 1

                    discovered_proofs.append({
                        'channel': 'Shared Drive Access',
                        'actor': f"{mem_info['name']} ({mem_dept})",
                        'target': f"{d_name} ({drive_dept})",
                        'detail': f"Assigned Role: {role} in {drive_dept}'s central space"
                    })
    except Exception as e:
        print(f"    [!] Shared Drive Membership audit note: {e}")

    # -------------------------------------------------------------------------
    # CHANNEL 2: GOOGLE DRIVE ACTIVITY (Cross-Department Edits & Shares)
    # -------------------------------------------------------------------------
    print("\n[*] Channel 2: Scanning Drive Activities (Shares, Edits on other Depts)...")
    try:
        res = reports_service.activities().list(
            userKey='all',
            applicationName='drive',
            maxResults=150
        ).execute()

        for item in res.get('items', []):
            actor_em = item.get('actor', {}).get('email', '').lower().strip()
            actor_info = user_directory.get(actor_em, {'name': actor_em, 'department': 'Operations (Unassigned)'})
            actor_dept = actor_info['department']

            for ev in item.get('events', []):
                ev_name = ev.get('name')
                pms = {p['name']: p for p in ev.get('parameters', [])}

                # Check for explicit shares
                target_user = pms.get('target_user', {}).get('stringValue', '').lower().strip()
                # Check for file owner if actor is editing someone else's file
                owner_user = pms.get('owner', {}).get('stringValue', '').lower().strip()
                doc_title = pms.get('doc_title', {}).get('stringValue', 'Document')

                counterpart_em = target_user or (owner_user if owner_user and owner_user != actor_em else None)
                if counterpart_em and ALLOWED_DOMAIN in counterpart_em and counterpart_em != actor_em:
                    target_info = user_directory.get(counterpart_em, {'name': counterpart_em, 'department': 'Operations (Unassigned)'})
                    target_dept = target_info['department']

                    if actor_dept != target_dept and 'Unassigned' not in actor_dept and 'Unassigned' not in target_dept:
                        cross_dept_matrix[(actor_dept, target_dept)] += 1
                        employee_pairs[(actor_em, counterpart_em, actor_dept, target_dept)] += 1

                        discovered_proofs.append({
                            'channel': f"Drive ({ev_name})",
                            'actor': f"{actor_info['name']} ({actor_dept})",
                            'target': f"{target_info['name']} ({target_dept})",
                            'detail': f"Collaborated on '{doc_title}'"
                        })
    except Exception as e:
        print(f"    [!] Drive Activity scan note: {e}")

    # -------------------------------------------------------------------------
    # CHANNEL 3: GOOGLE CALENDAR INVITES (Checking guest / attendees parameters)
    # -------------------------------------------------------------------------
    print("\n[*] Channel 3: Scanning Google Calendar for Inter-Department Sessions...")
    try:
        cal_res = reports_service.activities().list(
            userKey='all',
            applicationName='calendar',
            maxResults=150
        ).execute()

        for item in cal_res.get('items', []):
            actor_em = item.get('actor', {}).get('email', '').lower().strip()
            actor_info = user_directory.get(actor_em, {'name': actor_em, 'department': 'Operations (Unassigned)'})
            actor_dept = actor_info['department']

            for ev in item.get('events', []):
                pms = {p['name']: p for p in ev.get('parameters', [])}
                event_title = pms.get('event_title', {}).get('stringValue', 'Calendar Event')

                # Google Calendar stores guests under 'guest' or 'attendees' (multiValue)
                guests = pms.get('guest', {}).get('multiValue', []) or pms.get('attendees', {}).get('multiValue', [])
                for g in guests:
                    g_em = g.lower().strip()
                    if g_em and g_em != actor_em and ALLOWED_DOMAIN in g_em:
                        target_info = user_directory.get(g_em, {'name': g_em, 'department': 'Operations (Unassigned)'})
                        target_dept = target_info['department']

                        if actor_dept != target_dept and 'Unassigned' not in actor_dept and 'Unassigned' not in target_dept:
                            cross_dept_matrix[(actor_dept, target_dept)] += 1
                            employee_pairs[(actor_em, g_em, actor_dept, target_dept)] += 1

                            discovered_proofs.append({
                                'channel': 'Meeting Invite',
                                'actor': f"{actor_info['name']} ({actor_dept})",
                                'target': f"{target_info['name']} ({target_dept})",
                                'detail': f"Session: '{event_title}'"
                            })
    except Exception as e:
        print(f"    [!] Calendar scan note: {e}")

    # =========================================================================
    # DISPLAY PROVEN RESULTS
    # =========================================================================
    print("\n" + "=" * 85)
    print(" DISCOVERED CROSS-DEPARTMENT COLLABORATION PROOFS")
    print("=" * 85)

    if not discovered_proofs:
        print(" [!] No cross-department actions discovered across all 3 channels.")
    else:
        for idx, p in enumerate(discovered_proofs[:15], 1):
            print(f" {idx:02d}. [{p['channel']}]")
            print(f"     From:   {p['actor']}")
            print(f"     To:     {p['target']}")
            print(f"     Detail: {p['detail']}\n")

    print("=" * 85)
    print(" CROSS-DEPARTMENT COLLABORATION MATRIX (ACTUAL DEPARTMENT FLOWS)")
    print("=" * 85)
    print(f" {'SOURCE DEPARTMENT':<28} -> {'TARGET DEPARTMENT':<28} | {'INTERACTIONS':>14}")
    print("-" * 85)

    sorted_matrix = sorted(cross_dept_matrix.items(), key=lambda x: x[1], reverse=True)
    if sorted_matrix:
        for (src, tgt), count in sorted_matrix:
            print(f" {src:<28} -> {tgt:<28} | {count:>10} events")
    else:
        print(" No cross-department pairs found.")

    print("\n" + "=" * 85)
    print(" TOP EMPLOYEE / SPACE COLLABORATION PAIRS")
    print("=" * 85)
    sorted_emps = sorted(employee_pairs.items(), key=lambda x: x[1], reverse=True)
    for (actor, target, s_dept, t_dept), count in sorted_emps[:12]:
        print(f" • {actor} ({s_dept}) -> {target} ({t_dept}) : {count} interaction(s)")
    print("=" * 85 + "\n")


if __name__ == '__main__':
    probe_collaboration()