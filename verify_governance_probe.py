"""
Coolaire Consolidated Inc. (CCI) - Comprehensive User Governance, Privileges & Password Report
Multi-Channel Detection:
1. Canonical Department Mapping (Finance, Accounting, Warehouse, IT, Management, etc.)
2. Privilege Tiers: Super Admin, Delegated Admin, Standard User
3. Complete 180-Day Password History: IT Admin Resets vs. User Self-Service Changes
4. Specific User & Department Granular Breakdowns with CSV Export
Does NOT write to or modify any database tables.
"""

import os
import sys
import datetime
import csv
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
    'https://www.googleapis.com/auth/admin.reports.audit.readonly'
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

    if 'credit and collection' in raw_clean or 'credit & collection' in raw_clean or 'collection' in words or 'credit' in words:
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


def build_user_directory(dir_service):
    """Loads all corporate accounts and isolates privileges, department, and 2SV status."""
    users_dict = {}
    page_token = None

    print("[*] Ingesting all corporate accounts from Google Directory API...")
    while True:
        res = dir_service.users().list(
            customer='my_customer',
            projection='full',
            maxResults=500,
            pageToken=page_token
        ).execute(num_retries=3)

        for u in res.get('users', []):
            em = u.get('primaryEmail', '').lower().strip()
            name = u.get('name', {}).get('fullName', em)
            is_super = bool(u.get('isAdmin', False))
            is_delegated = bool(u.get('isDelegatedAdmin', False))
            is_2sv = bool(u.get('isEnrolledIn2Sv', False))
            is_suspended = bool(u.get('suspended', False))
            last_login = u.get('lastLoginTime', '')

            raw_dept = None
            for org in u.get('organizations', []):
                raw_dept = org.get('department') or org.get('title')
                if raw_dept:
                    break

            dept = match_department(raw_dept, em)

            if is_super:
                tier = "Super Admin (Root)"
            elif is_delegated:
                tier = "Delegated Admin"
            else:
                tier = "Standard User"

            users_dict[em] = {
                'email': em,
                'name': name,
                'department': dept,
                'privilege_tier': tier,
                'is_super_admin': is_super,
                'is_delegated_admin': is_delegated,
                'is_enrolled_in_2sv': is_2sv,
                'is_suspended': is_suspended,
                'last_login_time': last_login,
                'admin_resets': 0,
                'self_resets': 0,
                'total_resets': 0,
                'last_reset_date': 'None',
                'history': []
            }

        page_token = res.get('nextPageToken')
        if not page_token:
            break

    print(f"    -> Ingested {len(users_dict)} corporate accounts.")
    return users_dict


def audit_password_history(reports_service, users_map):
    """Audits entire 180-day retention window across Admin and Login Audit APIs."""
    total_admin_resets = 0
    total_self_resets = 0

    # 1. Admin Console Resets
    print("[*] Auditing Admin Console forced password resets (all pages)...")
    page_token = None
    while True:
        try:
            res = reports_service.activities().list(
                userKey='all',
                applicationName='admin',
                eventName='CHANGE_PASSWORD',
                maxResults=100,
                pageToken=page_token
            ).execute(num_retries=3)

            for item in res.get('items', []):
                admin_actor = item.get('actor', {}).get('email', '').lower().strip()
                t_str = item.get('id', {}).get('time', '')

                for ev in item.get('events', []):
                    pms = {p['name']: p.get('value') or p.get('stringValue') for p in ev.get('parameters', [])}
                    target_em = (pms.get('USER_EMAIL') or pms.get('TARGET_USER') or '').lower().strip()

                    if target_em in users_map:
                        u = users_map[target_em]
                        u['admin_resets'] += 1
                        u['total_resets'] += 1
                        u['history'].append({'timestamp': t_str, 'type': 'Admin Forced Reset', 'actor': admin_actor})
                        total_admin_resets += 1

            page_token = res.get('nextPageToken')
            if not page_token:
                break
        except Exception as e:
            print(f"    [!] Admin Audit page traversal note: {e}")
            break

    # 2. User Self-Service Changes & Recovery
    print("[*] Auditing User Self-Service Changes & Recovery Resets (all pages)...")
    page_token = None
    while True:
        try:
            res = reports_service.activities().list(
                userKey='all',
                applicationName='login',
                maxResults=100,
                pageToken=page_token
            ).execute(num_retries=3)

            for item in res.get('items', []):
                user_actor = item.get('actor', {}).get('email', '').lower().strip()
                t_str = item.get('id', {}).get('time', '')

                for ev in item.get('events', []):
                    ev_name = ev.get('name', '')
                    if ev_name in ['password_change', 'account_recovery_password_reset']:
                        if user_actor in users_map:
                            u = users_map[user_actor]
                            u['self_resets'] += 1
                            u['total_resets'] += 1
                            lbl = 'Recovery Reset' if ev_name == 'account_recovery_password_reset' else 'Self Change'
                            u['history'].append({'timestamp': t_str, 'type': lbl, 'actor': user_actor})
                            total_self_resets += 1

            page_token = res.get('nextPageToken')
            if not page_token:
                break
        except Exception as e:
            print(f"    [!] Login Audit page traversal note: {e}")
            break

    # Resolve last reset timestamp for each user
    for u in users_map.values():
        if u['history']:
            u['history'].sort(key=lambda x: x['timestamp'], reverse=True)
            u['last_reset_date'] = u['history'][0]['timestamp'][:10]

    return total_admin_resets, total_self_resets


def generate_governance_report():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"[!] Key file not found: {SERVICE_ACCOUNT_FILE}")
        sys.exit(1)

    print("=" * 105)
    print(" COOLAIRE CONSOLIDATED INC. - USER PRIVILEGES & PASSWORD GOVERNANCE REPORT")
    print(f" Domain: {ALLOWED_DOMAIN} | Delegated Admin: {ADMIN_EMAIL}")
    print(" Scope: Complete 180-Day Retained Google Audit History")
    print("=" * 105 + "\n")

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    ).with_subject(ADMIN_EMAIL)

    dir_service = build('admin', 'directory_v1', credentials=creds, cache_discovery=False)
    reports_service = build('admin', 'reports_v1', credentials=creds, cache_discovery=False)

    users_map = build_user_directory(dir_service)
    total_admin_resets, total_self_resets = audit_password_history(reports_service, users_map)

    # -------------------------------------------------------------------------
    # DATA AGGREGATION & ENABLEMENT CLASSIFICATION
    # -------------------------------------------------------------------------
    dept_users = defaultdict(list)
    dept_stats = defaultdict(lambda: {
        'total': 0, '2sv_count': 0, 'admins': 0, 'admin_resets': 0, 'self_resets': 0, 'total_resets': 0
    })

    for u in users_map.values():
        tot = u['total_resets']
        if tot >= 4:
            u['risk_category'] = "🔴 Chronic Resetter"
            u['recommendation'] = "Enroll in Corporate Password Manager"
        elif tot >= 2:
            u['risk_category'] = "🟡 Frequent Resetter"
            u['recommendation'] = "1-on-1 Workspace Credential Coaching"
        elif tot == 1:
            u['risk_category'] = "🟢 Routine Rotation"
            u['recommendation'] = "Normal (No Action Required)"
        else:
            u['risk_category'] = "⚪ Stable (0 Resets)"
            u['recommendation'] = "None (Good Security Habits)"

        d = u['department']
        dept_users[d].append(u)
        dept_stats[d]['total'] += 1
        if u['is_enrolled_in_2sv']:
            dept_stats[d]['2sv_count'] += 1
        if u['is_super_admin'] or u['is_delegated_admin']:
            dept_stats[d]['admins'] += 1
        dept_stats[d]['admin_resets'] += u['admin_resets']
        dept_stats[d]['self_resets'] += u['self_resets']
        dept_stats[d]['total_resets'] += tot

    unique_resetters = [u for u in users_map.values() if u['total_resets'] > 0]
    total_resets_domain = total_admin_resets + total_self_resets

    # =========================================================================
    # SECTION 1: EXECUTIVE KPI SUMMARY
    # =========================================================================
    print("\n" + "=" * 105)
    print(" SECTION 1: EXECUTIVE GOVERNANCE & CREDENTIAL KPI SUMMARY")
    print("=" * 105)
    print(f" • Total Active/Suspended Accounts:       {len(users_map)}")
    print(f" • Unique Users Who Reset Passwords:      {len(unique_resetters)} ({round(len(unique_resetters)/max(1, len(users_map))*100, 1)}% of domain)")
    print(f" • Total Password Reset Events:           {total_resets_domain} in 180 days")
    print(f"   ├─ IT Admin Forced Resets (Ticket Cost): {total_admin_resets}")
    print(f"   └─ User Self-Service / Recoveries:       {total_self_resets}")
    print(f" • Chronic Resetters (3+ times):          {sum(1 for u in unique_resetters if u['total_resets'] >= 3)} accounts")
    print(f" • Privileged Administrators:             {sum(1 for u in users_map.values() if u['is_super_admin'] or u['is_delegated_admin'])} accounts")

    # =========================================================================
    # SECTION 2: DEPARTMENTAL DISRUPTION & PRIVILEGE MATRIX
    # =========================================================================
    print("\n" + "=" * 105)
    print(" SECTION 2: DEPARTMENTAL DISRUPTION & PRIVILEGE MATRIX")
    print("=" * 105)
    print(f" {'DEPARTMENT':<24} | {'USERS':>6} | {'2SV %':>7} | {'ADMINS':>7} | {'IT RESETS':>10} | {'SELF RESETS':>12} | {'TOTAL RESETS':>12}")
    print("-" * 105)

    sorted_depts = sorted(dept_stats.items(), key=lambda x: (x[1]['total_resets'], x[1]['total']), reverse=True)
    for dept_name, s in sorted_depts:
        tot_m = max(1, s['total'])
        two_fa_str = f"{round((s['2sv_count'] / tot_m) * 100)}%"
        print(f" {dept_name:<24} | {s['total']:>6} | {two_fa_str:>7} | {s['admins']:>7} | {s['admin_resets']:>10} | {s['self_resets']:>12} | {s['total_resets']:>12}")

    # =========================================================================
    # SECTION 3: SPECIFIC USERS GROUPED BY DEPARTMENT
    # =========================================================================
    print("\n" + "=" * 105)
    print(" SECTION 3: SPECIFIC USERS & CORRESPONDING DEPARTMENTS (GROUPED AUDIT)")
    print("=" * 105)

    for dept_name, _ in sorted_depts:
        members = dept_users[dept_name]
        members.sort(key=lambda x: (x['total_resets'], x['admin_resets']), reverse=True)

        print(f"\n ► DEPARTMENT: {dept_name.upper()} ({len(members)} Users)")
        print(f"   {'EMPLOYEE NAME':<22} | {'EMAIL ADDRESS':<32} | {'PRIVILEGE':<15} | {'2SV':>4} | {'IT':>3} | {'SELF':>4} | {'TOT':>4} | {'LAST RESET':<10} | {'RISK STATUS'}")
        print("   " + "-" * 115)

        for m in members:
            e_name = m['name'][:22]
            e_mail = m['email'][:32]
            p_tier = m['privilege_tier'][:15]
            two_sv = "YES" if m['is_enrolled_in_2sv'] else "NO"
            print(f"   {e_name:<22} | {e_mail:<32} | {p_tier:<15} | {two_sv:>4} | {m['admin_resets']:>3} | {m['self_resets']:>4} | {m['total_resets']:>4} | {m['last_reset_date']:<10} | {m['risk_category']}")

    # =========================================================================
    # SECTION 4: EXPORT TO CSV
    # =========================================================================
    csv_filename = os.path.join(BASE_DIR, "cci_user_governance_report.csv")
    print("\n" + "=" * 105)
    print(f" SECTION 4: EXPORTING DETAILED AUDIT TO CSV: {csv_filename}")
    print("=" * 105)

    all_users_sorted = sorted(users_map.values(), key=lambda x: (x['department'], -x['total_resets']))
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
                    u['total_resets'], u['last_reset_date'], u['risk_category'],
                    u['recommendation']
                ])
        print(f" [✓] CSV Report successfully generated with {len(all_users_sorted)} user rows.")
    except Exception as e:
        print(f" [!] CSV Export Note: {e}")

    print("=" * 105 + "\n")


if __name__ == '__main__':
    generate_governance_report()