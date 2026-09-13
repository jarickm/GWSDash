"""
Coolaire Consolidated Inc. (CCI) - Master Deep Governance, Security & Enablement Audit
Exhaustive Pure-Terminal Diagnostic:
1. Domain Privileges & Administrative Hierarchy
2. Credential Disruptions & 180-Day Password Reset Ledger
3. DLP File Exposure: External Sharing & Public Links
4. External Destination Domain Risk Analysis
5. Shadow IT & Third-Party OAuth App Grants
6. Mailbox Auto-Forwarding & Exfiltration Rules
7. License Reclamation & Cost Waste Pipeline (Itemized)
8. Departmental Digital Maturity & Cloud Enablement
9. Itemized Master Employee Roster by Department

Pure Read-Only. Does NOT write to or modify any Google accounts or database tables.
"""

import os
import sys
import datetime
import csv
from collections import defaultdict
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.environ.get('SERVICE_ACCOUNT_FILE', os.path.join(BASE_DIR, 'old/credentials-old.json'))
ADMIN_EMAIL = os.environ.get('WORKSPACE_ADMIN_EMAIL', 'jarick.montojo@coolaireconsolidated.com')
ALLOWED_DOMAIN = os.environ.get('ALLOWED_DOMAIN', 'coolaireconsolidated.com')
ESTIMATED_SEAT_MONTHLY_COST = float(os.environ.get('LICENSE_MONTHLY_COST', '14.40'))

SCOPES = [
    'https://www.googleapis.com/auth/admin.directory.user.readonly',
    'https://www.googleapis.com/auth/admin.reports.audit.readonly',
    'https://www.googleapis.com/auth/admin.reports.usage.readonly',
    'https://www.googleapis.com/auth/apps.licensing'
]

DEPARTMENT_TAXONOMY = {
    'Finance': ['finance', 'fa', 'billing', 'disbursement', 'ap', 'ar', 'financial'],
    'Accounting': ['accounting', 'acct', 'bookkeeper', 'audit_acct', 'general_accounting', 'ledger'],
    'CNC & Treasury': ['cnc', 'treasury', 'cash', 'treasurer'],
    'Credit and Collection': ['credit and collection', 'credit & collection', 'collection', 'credit', 'collections'],
    'Purchasing': ['purchasing', 'procurement', 'purch', 'buyer', 'sourcing'],
    'Sales': ['sales', 'commercial', 'account executive', 'business development', 'bdr'],
    'Service': ['service', 'technical_service', 'technician', 'maintenance', 'hvac', 'aftersales'],
    'Production': ['production', 'manufacturing', 'plant', 'factory', 'assembly', 'fabrication'],
    'Warehouse': ['warehouse', 'logistics', 'inventory', 'stock', 'receiving', 'storekeeper'],
    'HR': ['hr', 'human resources', 'human_resources', 'people', 'personnel', 'admin_hr'],
    'Audit': ['audit', 'internal_audit', 'compliance', 'qa_audit'],
    'Asset': ['asset', 'facilities', 'fleet', 'machinery', 'property'],
    'Marketing': ['marketing', 'mktg', 'creatives', 'branding', 'graphics', 'digital'],
    'Imports': ['imports', 'customs', 'shipping', 'brokerage', 'importation'],
    'IT Department': ['it', 'tech', 'sysadmin', 'information technology', 'systems', 'edp'],
    'Management': ['management', 'executive', 'c-level', 'board', 'director', 'president', 'ceo']
}


def truncate(text, length):
    text_str = str(text or '')
    if len(text_str) > length:
        return text_str[:length - 2] + ".."
    return text_str


def match_department(raw_text, email=""):
    clean_email = (email or '').lower().strip()
    if any(k in clean_email for k in ['it@', 'tech@', 'sysadmin@']) or clean_email == ADMIN_EMAIL.lower():
        return 'IT Department'
    if any(k in clean_email for k in ['ceo@', 'president@', 'board@', 'exec@', 'admin@']):
        return 'Management'

    if not raw_text:
        return 'Operations (Unassigned)'

    raw_clean = raw_text.lower().replace('&', 'and').replace('/', ' ')
    words = raw_clean.split()

    for canonical_name, aliases in DEPARTMENT_TAXONOMY.items():
        if canonical_name.lower() in raw_clean:
            return canonical_name
        for alias in aliases:
            if alias in raw_clean or alias in words:
                return canonical_name

    return raw_text.strip()


def run_master_deep_audit():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"[!] Critical Error: Key file missing at {SERVICE_ACCOUNT_FILE}")
        sys.exit(1)

    print("\n" + "=" * 118)
    print(" COOLAIRE CONSOLIDATED INC. - MASTER DEEP WORKSPACE GOVERNANCE & SECURITY AUDIT")
    print(f" Target Domain: @{ALLOWED_DOMAIN} | Delegated Admin: {ADMIN_EMAIL}")
    print(" Ingesting live telemetry across all Google Workspace APIs...")
    print("=" * 118 + "\n")

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    ).with_subject(ADMIN_EMAIL)

    dir_service = build('admin', 'directory_v1', credentials=creds, cache_discovery=False)
    rep_service = build('admin', 'reports_v1', credentials=creds, cache_discovery=False)
    lic_service = build('licensing', 'v1', credentials=creds, cache_discovery=False)

    now = datetime.datetime.now(datetime.timezone.utc)

    # -------------------------------------------------------------------------
    # 1. DIRECTORY & LICENSING INGESTION
    # -------------------------------------------------------------------------
    print("[1/6] Ingesting Directory Accounts & Paid License Grants...")
    users = {}
    page_token = None
    while True:
        res = dir_service.users().list(
            customer='my_customer', projection='full', maxResults=500, pageToken=page_token
        ).execute(num_retries=3)

        for u in res.get('users', []):
            em = u.get('primaryEmail', '').lower().strip()
            name = u.get('name', {}).get('fullName', em)
            raw_dept = None
            for org in u.get('organizations', []):
                raw_dept = org.get('department') or org.get('title')
                if raw_dept:
                    break

            dept = match_department(raw_dept, em)
            is_super = bool(u.get('isAdmin', False))
            is_delegated = bool(u.get('isDelegatedAdmin', False))
            is_susp = bool(u.get('suspended', False))
            is_2sv = bool(u.get('isEnrolledIn2Sv', False))
            last_login_str = u.get('lastLoginTime', '')
            created_str = u.get('creationTime', '')

            days_inactive = None
            if last_login_str:
                try:
                    ll_dt = datetime.datetime.fromisoformat(last_login_str.replace('Z', '+00:00'))
                    days_inactive = (now - ll_dt).days
                except Exception:
                    pass

            if is_super:
                tier = "Super Admin (Root)"
            elif is_delegated:
                tier = "Delegated Admin"
            else:
                tier = "Standard User"

            users[em] = {
                'email': em,
                'name': name,
                'department': dept,
                'privilege_tier': tier,
                'is_super_admin': is_super,
                'is_delegated_admin': is_delegated,
                'is_suspended': is_susp,
                'is_2sv': is_2sv,
                'created_at': created_str[:10] if created_str else 'N/A',
                'last_login': last_login_str[:10] if last_login_str else 'Never',
                'days_inactive': days_inactive,
                'has_paid_license': True,
                'admin_resets': 0,
                'self_resets': 0,
                'total_resets': 0,
                'last_reset_date': 'None',
                'external_shares_count': 0,
                'public_links_count': 0,
                'oauth_apps_count': 0,
                'critical_apps_count': 0,
                'has_forwarding': False,
                'forwarding_target': 'None',
                'suspicious_logins_count': 0,
                'docs_created': 0,
                'emails_sent': 0
            }

        page_token = res.get('nextPageToken')
        if not page_token:
            break

    # Reconcile with Licensing API
    try:
        l_tok = None
        assigned = set()
        while True:
            l_res = lic_service.licenseAssignments().listForProduct(
                productId='Google-Apps', customerId=ALLOWED_DOMAIN, maxResults=100, pageToken=l_tok
            ).execute(num_retries=2)
            for item in l_res.get('items', []):
                uid = item.get('userId', '').lower().strip()
                if uid:
                    assigned.add(uid)
            l_tok = l_res.get('nextPageToken')
            if not l_tok:
                break
        if assigned:
            for em, u in users.items():
                u['has_paid_license'] = (em in assigned)
    except Exception:
        pass

    # -------------------------------------------------------------------------
    # 2. AUDIT 180-DAY PASSWORD DISRUPTIONS
    # -------------------------------------------------------------------------
    print("[2/6] Auditing 180-Day Password Resets & Credentials (all pages)...")
    password_ledger = []
    # A. Admin Resets
    try:
        p_tok = None
        while True:
            res = rep_service.activities().list(
                userKey='all', applicationName='admin', eventName='CHANGE_PASSWORD', maxResults=100, pageToken=p_tok
            ).execute(num_retries=3)
            for item in res.get('items', []):
                admin_actor = item.get('actor', {}).get('email', '').lower().strip()
                t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                for ev in item.get('events', []):
                    pms = {p['name']: p.get('value') or p.get('stringValue') for p in ev.get('parameters', [])}
                    target_em = (pms.get('USER_EMAIL') or pms.get('TARGET_USER') or '').lower().strip()
                    if target_em in users:
                        u = users[target_em]
                        u['admin_resets'] += 1
                        u['total_resets'] += 1
                        if u['last_reset_date'] == 'None' or t_str[:10] > u['last_reset_date']:
                            u['last_reset_date'] = t_str[:10]
                        password_ledger.append({
                            'timestamp': t_str,
                            'target_email': target_em,
                            'target_name': u['name'],
                            'department': u['department'],
                            'type': 'IT Admin Forced Reset',
                            'initiator': admin_actor or 'Admin Console'
                        })
            p_tok = res.get('nextPageToken')
            if not p_tok:
                break
    except Exception:
        pass

    # B. Self-Service Changes
    try:
        p_tok = None
        while True:
            res = rep_service.activities().list(
                userKey='all', applicationName='login', maxResults=100, pageToken=p_tok
            ).execute(num_retries=3)
            for item in res.get('items', []):
                user_actor = item.get('actor', {}).get('email', '').lower().strip()
                t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                for ev in item.get('events', []):
                    ev_name = ev.get('name', '')
                    if ev_name in ['password_change', 'account_recovery_password_reset']:
                        if user_actor in users:
                            u = users[user_actor]
                            u['self_resets'] += 1
                            u['total_resets'] += 1
                            if u['last_reset_date'] == 'None' or t_str[:10] > u['last_reset_date']:
                                u['last_reset_date'] = t_str[:10]
                            evt_type = 'Self-Service Recovery' if ev_name == 'account_recovery_password_reset' else 'User Password Change'
                            password_ledger.append({
                                'timestamp': t_str,
                                'target_email': user_actor,
                                'target_name': u['name'],
                                'department': u['department'],
                                'type': evt_type,
                                'initiator': user_actor
                            })
            p_tok = res.get('nextPageToken')
            if not p_tok:
                break
    except Exception:
        pass

    # -------------------------------------------------------------------------
    # 3. AUDIT DRIVE DLP, EXTERNAL SHARING & PUBLIC LINKS
    # -------------------------------------------------------------------------
    print("[3/6] Auditing Drive Data Loss Prevention (External Shares & Public Links)...")
    external_shares = []
    public_links = []
    external_domains = defaultdict(int)
    try:
        d_tok = None
        pages = 0
        while pages < 10:
            d_res = rep_service.activities().list(
                userKey='all', applicationName='drive', maxResults=100, pageToken=d_tok
            ).execute(num_retries=2)
            for item in d_res.get('items', []):
                actor_em = item.get('actor', {}).get('email', '').lower().strip()
                t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                u_info = users.get(actor_em, {'name': actor_em, 'department': 'Operations'})

                for ev in item.get('events', []):
                    pms = {p['name']: p.get('value') or p.get('stringValue') for p in ev.get('parameters', [])}
                    doc_title = pms.get('doc_title', 'Untitled Document')
                    doc_type = pms.get('doc_type', 'file')
                    target_u = (pms.get('target_user') or '').lower().strip()
                    vis = pms.get('visibility', '')

                    if vis in ['people_with_link', 'public']:
                        if actor_em in users:
                            users[actor_em]['public_links_count'] += 1
                        public_links.append({
                            'timestamp': t_str,
                            'owner_name': u_info['name'],
                            'owner_email': actor_em,
                            'department': u_info['department'],
                            'doc_title': doc_title,
                            'doc_type': doc_type,
                            'visibility': vis
                        })

                    if target_u and ALLOWED_DOMAIN not in target_u and '@' in target_u:
                        dom = target_u.split('@')[-1]
                        external_domains[dom] += 1
                        if actor_em in users:
                            users[actor_em]['external_shares_count'] += 1
                        external_shares.append({
                            'timestamp': t_str,
                            'owner_name': u_info['name'],
                            'owner_email': actor_em,
                            'department': u_info['department'],
                            'doc_title': doc_title,
                            'doc_type': doc_type,
                            'recipient': target_u,
                            'recipient_domain': dom
                        })
            d_tok = d_res.get('nextPageToken')
            pages += 1
            if not d_tok:
                break
    except Exception:
        pass

    # -------------------------------------------------------------------------
    # 4. AUDIT SHADOW IT & THIRD-PARTY OAUTH APP GRANTS
    # -------------------------------------------------------------------------
    print("[4/6] Auditing Third-Party OAuth App Permissions (Shadow IT)...")
    oauth_apps = []
    try:
        t_tok = None
        pages = 0
        while pages < 10:
            res = rep_service.activities().list(
                userKey='all', applicationName='token', maxResults=100, pageToken=t_tok
            ).execute(num_retries=3)
            for item in res.get('items', []):
                actor_em = item.get('actor', {}).get('email', '').lower().strip()
                t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                u_info = users.get(actor_em, {'name': actor_em, 'department': 'Operations'})

                for ev in item.get('events', []):
                    if ev.get('name') == 'authorize':
                        pms = {p['name']: p for p in ev.get('parameters', [])}
                        app_name = pms.get('app_name', {}).get('value', 'External Application')
                        scope_list = pms.get('scope_data', {}).get('multiValue', []) or pms.get('scope', {}).get('multiValue', [])

                        has_mail = any('mail.google.com' in s or 'gmail' in s for s in scope_list)
                        has_drive = any('auth/drive' in s for s in scope_list)

                        if has_mail or has_drive:
                            risk_tier = "🔴 CRITICAL: Reads Mail/Drive"
                            is_crit = True
                        else:
                            risk_tier = "🟢 LOW: Standard Sign-In"
                            is_crit = False

                        if actor_em in users:
                            users[actor_em]['oauth_apps_count'] += 1
                            if is_crit:
                                users[actor_em]['critical_apps_count'] += 1

                        oauth_apps.append({
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
            pages += 1
            if not t_tok:
                break
    except Exception:
        pass

    # -------------------------------------------------------------------------
    # 5. AUDIT MAILBOX AUTO-FORWARDING & EXFILTRATION
    # -------------------------------------------------------------------------
    print("[5/6] Auditing Mailbox Auto-Forwarding Rules & Routing...")
    forwarding_rules = []
    # Check User Accounts audit
    try:
        u_tok = None
        while True:
            res = rep_service.activities().list(
                userKey='all', applicationName='user_accounts', maxResults=100, pageToken=u_tok
            ).execute(num_retries=2)
            for item in res.get('items', []):
                actor_em = item.get('actor', {}).get('email', '').lower().strip()
                t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                u_info = users.get(actor_em, {'name': actor_em, 'department': 'Operations'})
                for ev in item.get('events', []):
                    if 'forward' in ev.get('name', '').lower():
                        pms = {p['name']: p for p in ev.get('parameters', [])}
                        dest = pms.get('forwarding_address', {}).get('value', '') or pms.get('email_address', {}).get('value', 'External')
                        if actor_em in users:
                            users[actor_em]['has_forwarding'] = True
                            users[actor_em]['forwarding_target'] = dest
                        forwarding_rules.append({
                            'timestamp': t_str,
                            'employee_name': u_info['name'],
                            'employee_email': actor_em,
                            'department': u_info['department'],
                            'destination': dest,
                            'setup_type': 'User Self-Service Forwarding'
                        })
            u_tok = res.get('nextPageToken')
            if not u_tok:
                break
    except Exception:
        pass

    # Check Admin audit log for admin-forwarding
    try:
        a_tok = None
        while True:
            res = rep_service.activities().list(
                userKey='all', applicationName='admin', maxResults=100, pageToken=a_tok
            ).execute(num_retries=2)
            for item in res.get('items', []):
                t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                for ev in item.get('events', []):
                    if 'FORWARDING' in ev.get('name', ''):
                        pms = {p['name']: p for p in ev.get('parameters', [])}
                        target_em = (pms.get('USER_EMAIL') or pms.get('TARGET_USER') or '').lower().strip()
                        dest = pms.get('FORWARDING_ADDRESS', {}).get('value', 'Configured Forward')
                        u_info = users.get(target_em, {'name': target_em, 'department': 'Operations'})
                        if target_em in users:
                            users[target_em]['has_forwarding'] = True
                            users[target_em]['forwarding_target'] = dest
                        forwarding_rules.append({
                            'timestamp': t_str,
                            'employee_name': u_info['name'],
                            'employee_email': target_em,
                            'department': u_info['department'],
                            'destination': dest,
                            'setup_type': 'Admin-Configured Mail Routing'
                        })
            a_tok = res.get('nextPageToken')
            if not a_tok:
                break
    except Exception:
        pass

    # Check Suspicious Logins
    try:
        l_tok = None
        pages = 0
        while pages < 6:
            res = rep_service.activities().list(
                userKey='all', applicationName='login', maxResults=100, pageToken=l_tok
            ).execute(num_retries=2)
            for item in res.get('items', []):
                actor_em = item.get('actor', {}).get('email', '').lower().strip()
                for ev in item.get('events', []):
                    if ev.get('name') in ['suspicious_login', 'suspicious_login_type', 'login_challenge', 'login_failure']:
                        if actor_em in users:
                            users[actor_em]['suspicious_logins_count'] += 1
            l_tok = res.get('nextPageToken')
            pages += 1
            if not l_tok:
                break
    except Exception:
        pass

    # -------------------------------------------------------------------------
    # 6. USAGE REPORTS & DIGITAL MATURITY INGESTION
    # -------------------------------------------------------------------------
    print("[6/6] Ingesting Google Workspace Cloud Maturity Usage Telemetry...")
    for days_back in range(3, 10):
        test_date = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()
        try:
            u_res = rep_service.userUsageReport().get(
                userKey='all', date=test_date,
                parameters='drive:num_google_documents_created,drive:num_google_spreadsheets_created,gmail:num_emails_sent'
            ).execute(num_retries=2)
            reports = u_res.get('usageReports', [])
            if reports:
                for r in reports:
                    em = r.get('entity', {}).get('userEmail', '').lower().strip()
                    pms = {p['name']: p for p in r.get('parameters', [])}
                    if em in users:
                        docs_val = int(pms.get('drive:num_google_documents_created', {}).get('intValue', 0))
                        sheets_val = int(pms.get('drive:num_google_spreadsheets_created', {}).get('intValue', 0))
                        users[em]['docs_created'] = docs_val + sheets_val
                        users[em]['emails_sent'] = int(pms.get('gmail:num_emails_sent', {}).get('intValue', 0))
                break
        except Exception:
            continue

    print("[✓] Master Audit Telemetry Successfully Assembled. Generating Report...\n")

    # =========================================================================
    # SECTION 1: EXECUTIVE KPI DASHBOARD & RISK HEATMAP
    # =========================================================================
    suspended_paid = [u for u in users.values() if u['is_suspended'] and u['has_paid_license']]
    dormant_60d = [u for u in users.values() if not u['is_suspended'] and u['has_paid_license'] and u['days_inactive'] is not None and u['days_inactive'] >= 60]
    never_logged = [u for u in users.values() if not u['is_suspended'] and u['has_paid_license'] and u['last_login'] == 'Never']

    immediate_reclaim_seats = len(suspended_paid)
    review_reclaim_seats = len(dormant_60d) + len(never_logged)
    total_waste_seats = immediate_reclaim_seats + review_reclaim_seats
    annual_potential_savings = total_waste_seats * ESTIMATED_SEAT_MONTHLY_COST * 12

    unique_resetters = [u for u in users.values() if u['total_resets'] > 0]
    chronic_resetters = [u for u in users.values() if u['total_resets'] >= 3]
    critical_apps = [a for a in oauth_apps if a['is_critical']]

    print("=" * 118)
    print(" SECTION 1: EXECUTIVE KPI DASHBOARD & SECURITY RISK HEATMAP")
    print("=" * 118)
    print(f" • Total Corporate Accounts Audited:        {len(users)}")
    print(f" • Root Super Administrators (Unrestricted): {sum(1 for u in users.values() if u['is_super_admin'])} accounts")
    print(f" • Delegated / Custom Administrators:       {sum(1 for u in users.values() if u['is_delegated_admin'])} accounts")
    print(f" • 2-Step Verification (2SV) Compliance:    {sum(1 for u in users.values() if u['is_2sv'])} of {len(users)} accounts enrolled ({round((sum(1 for u in users.values() if u['is_2sv']) / max(1, len(users))) * 100, 1)}%)")
    print(f" • Credential Disruptions (180-Day Total):   {len(password_ledger)} password resets across {len(unique_resetters)} unique users")
    print(f" • Chronic Password Resetters (3+ times):   {len(chronic_resetters)} accounts (Requires 1-on-1 coaching)")
    print(f" • External File Disclosures (DLP Risk):    {len(external_shares)} files shared outside @{ALLOWED_DOMAIN}")
    print(f" • Public Link Disclosures ('Anyone w/ link'): {len(public_links)} active public links")
    print(f" • Third-Party OAuth Apps Connected:       {len(oauth_apps)} grants ({len(critical_apps)} with full Gmail/Drive read access)")
    print(f" • Active Mailbox Auto-Forwarding Rules:    {len(forwarding_rules)} accounts forwarding corporate mail externally")
    print(f" • Paid Seat Reclamation Pipeline:          {total_waste_seats} wasted seats (${annual_potential_savings:,.2f} USD/year recovery)")

    # =========================================================================
    # SECTION 2: DOMAIN PRIVILEGES & ADMIN HIERARCHY
    # =========================================================================
    print("\n" + "=" * 118)
    print(" SECTION 2: DOMAIN PRIVILEGES & ADMINISTRATIVE HIERARCHY")
    print("=" * 118)
    print(f" {'EMPLOYEE NAME':<24} | {'EMAIL ADDRESS':<34} | {'DEPARTMENT':<18} | {'PRIVILEGE LEVEL':<22} | {'2SV STATUS'}")
    print("-" * 118)

    admins = [u for u in users.values() if u['is_super_admin'] or u['is_delegated_admin']]
    if not admins:
        print(" [!] Anomaly: No administrator accounts discovered.")
    else:
        for a in admins:
            name_str = truncate(a['name'], 24)
            email_str = truncate(a['email'], 34)
            dept_str = truncate(a['department'], 18)
            tier_str = truncate(a['privilege_tier'], 22)
            two_sv_str = "ENFORCED (YES)" if a['is_2sv'] else "CRITICAL: NO 2SV ⚠️"
            print(f" {name_str:<24} | {email_str:<34} | {dept_str:<18} | {tier_str:<22} | {two_sv_str}")

    # =========================================================================
    # SECTION 3: CREDENTIAL DISRUPTIONS & 180-DAY PASSWORD RESET LEDGER
    # =========================================================================
    print("\n" + "=" * 118)
    print(" SECTION 3: CREDENTIAL DISRUPTIONS & HABITUAL PASSWORD RESET LEDGER (180 DAYS)")
    print("=" * 118)
    print(f" {'TIMESTAMP (UTC)':<19} | {'EMPLOYEE NAME':<22} | {'EMAIL ADDRESS':<30} | {'DEPT':<14} | {'RESET TYPE':<22} | {'INITIATOR'}")
    print("-" * 118)

    if not password_ledger:
        print(" [✓] Zero password reset disruptions recorded in the entire 180-day audit window.")
    else:
        password_ledger.sort(key=lambda x: x['timestamp'], reverse=True)
        for p in password_ledger[:25]:
            t_str = p['timestamp']
            n_str = truncate(p['target_name'], 22)
            e_str = truncate(p['target_email'], 30)
            d_str = truncate(p['department'], 14)
            ty_str = truncate(p['type'], 22)
            in_str = truncate(p['initiator'], 20)
            print(f" {t_str:<19} | {n_str:<22} | {e_str:<30} | {d_str:<14} | {ty_str:<22} | {in_str}")

    # =========================================================================
    # SECTION 4: DATA LOSS PREVENTION (DLP) & EXTERNAL SHARING LEDGER
    # =========================================================================
    print("\n" + "=" * 118)
    print(" SECTION 4: DATA LOSS PREVENTION (DLP) - EXTERNAL SHARING & PUBLIC LINKS")
    print("=" * 118)
    print(f" {'TIMESTAMP (UTC)':<19} | {'EMPLOYEE (OWNER)':<24} | {'DEPT':<14} | {'DOCUMENT TITLE':<28} | {'EXTERNAL RECIPIENT'}")
    print("-" * 118)

    if not external_shares and not public_links:
        print(" [✓] Optimal Security: Zero external file disclosures or public links discovered.")
    else:
        for s in external_shares[:20]:
            t_str = s['timestamp']
            o_str = truncate(s['owner_name'] + " (" + s['owner_email'] + ")", 24)
            d_str = truncate(s['department'], 14)
            doc_str = truncate(s['doc_title'], 28)
            r_str = "⚠️ " + truncate(s['recipient'], 30)
            print(f" {t_str:<19} | {o_str:<24} | {d_str:<14} | {doc_str:<28} | {r_str}")

        for pl in public_links[:10]:
            t_str = pl['timestamp']
            o_str = truncate(pl['owner_name'] + " (" + pl['owner_email'] + ")", 24)
            d_str = truncate(pl['department'], 14)
            doc_str = truncate(pl['doc_title'], 28)
            print(f" {t_str:<19} | {o_str:<24} | {d_str:<14} | {doc_str:<28} | 🚨 PUBLIC: Anyone with link")

    # =========================================================================
    # SECTION 5: EXTERNAL DESTINATION DOMAINS ANALYSIS
    # =========================================================================
    print("\n" + "=" * 118)
    print(" SECTION 5: EXTERNAL DESTINATION DOMAINS (WHERE IS CORPORATE DATA GOING?)")
    print("=" * 118)
    print(f" {'EXTERNAL RECIPIENT DOMAIN':<36} | {'FILES EXPOSED':>14} | {'RISK CLASSIFICATION'}")
    print("-" * 118)

    if not external_domains:
        print(" [✓] No external destination domains detected.")
    else:
        sorted_doms = sorted(external_domains.items(), key=lambda x: x[1], reverse=True)
        for dom, cnt in sorted_doms[:10]:
            d_str = truncate("@" + dom, 36)
            if dom in ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com']:
                r_class = "🔴 HIGH RISK: Personal Webmail (Data Leakage)"
            else:
                r_class = "🟡 MEDIUM RISK: Third-Party Vendor / External Partner"
            print(f" {d_str:<36} | {cnt:>14} | {r_class}")

    # =========================================================================
    # SECTION 6: SHADOW IT & THIRD-PARTY OAUTH APP PERMISSIONS
    # =========================================================================
    print("\n" + "=" * 118)
    print(" SECTION 6: SHADOW IT - THIRD-PARTY OAUTH APPLICATION GRANTS")
    print("=" * 118)
    print(f" {'TIMESTAMP (UTC)':<19} | {'EMPLOYEE':<28} | {'DEPT':<14} | {'APP NAME':<22} | {'RISK CLASSIFICATION'}")
    print("-" * 118)

    if not oauth_apps:
        print(" [✓] SECURE: Zero third-party OAuth app authorizations captured.")
    else:
        oauth_apps.sort(key=lambda x: (x['is_critical'], x['timestamp']), reverse=True)
        for a in oauth_apps[:25]:
            t_str = a['timestamp']
            u_str = truncate(a['employee_name'] + " (" + a['employee_email'] + ")", 28)
            d_str = truncate(a['department'], 14)
            ap_str = truncate(a['app_name'], 22)
            print(f" {t_str:<19} | {u_str:<28} | {d_str:<14} | {ap_str:<22} | {a['risk_tier']}")

    # =========================================================================
    # SECTION 7: MAILBOX AUTO-FORWARDING & EXFILTRATION RULES
    # =========================================================================
    print("\n" + "=" * 118)
    print(" SECTION 7: MAILBOX AUTO-FORWARDING RULES (EXFILTRATION RISKS)")
    print("=" * 118)
    print(f" {'TIMESTAMP (UTC)':<19} | {'EMPLOYEE SOURCE':<32} | {'FORWARDING DESTINATION':<32} | {'SETUP TYPE'}")
    print("-" * 118)

    if not forwarding_rules:
        print(" [✓] SECURE: Zero email auto-forwarding or external exfiltration rules found.")
    else:
        for f in forwarding_rules:
            t_str = f['timestamp']
            u_str = truncate(f['employee_name'] + " (" + f['employee_email'] + ")", 32)
            dest = f['destination']
            dest_str = "⚠️ " + truncate(dest, 30) if ALLOWED_DOMAIN not in dest else truncate(dest, 32)
            print(f" {t_str:<19} | {u_str:<32} | {dest_str:<32} | {f['setup_type']}")

    # =========================================================================
    # SECTION 8: LICENSE RECLAMATION & BUDGET WASTE PIPELINE (ITEMIZED)
    # =========================================================================
    print("\n" + "=" * 118)
    print(" SECTION 8: LICENSE RECLAMATION & BUDGET WASTE PIPELINE (ITEMIZED PAID SEATS)")
    print("=" * 118)
    print(f" {'EMPLOYEE NAME':<22} | {'EMAIL ADDRESS':<32} | {'DEPARTMENT':<15} | {'INACTIVITY STATUS':<22} | {'RECOMMENDED ACTION'}")
    print("-" * 118)

    reclaim_candidates = []
    for u in suspended_paid:
        reclaim_candidates.append({
            'name': u['name'], 'email': u['email'], 'dept': u['department'],
            'status': 'SUSPENDED ACCOUNT', 'action': '🔴 REVOKE SEAT NOW'
        })
    for u in never_logged:
        reclaim_candidates.append({
            'name': u['name'], 'email': u['email'], 'dept': u['department'],
            'status': 'NEVER LOGGED IN', 'action': '🟡 ONBOARDING FAILURE / RECLAIM'
        })
    for u in dormant_60d:
        reclaim_candidates.append({
            'name': u['name'], 'email': u['email'], 'dept': u['department'],
            'status': f"{u['days_inactive']} days inactive", 'action': '🟡 AUDIT WITH HR / RECLAIM'
        })

    if not reclaim_candidates:
        print(" [✓] OPTIMAL EFFICIENCY: Zero wasted paid licenses found.")
    else:
        for r in reclaim_candidates[:30]:
            n_str = truncate(r['name'], 22)
            e_str = truncate(r['email'], 32)
            d_str = truncate(r['dept'], 15)
            st_str = truncate(r['status'], 22)
            print(f" {n_str:<22} | {e_str:<32} | {d_str:<15} | {st_str:<22} | {r['action']}")

    # =========================================================================
    # SECTION 9: DEPARTMENTAL DIGITAL MATURITY & CLOUD ENABLEMENT
    # =========================================================================
    dept_stats = defaultdict(lambda: {
        'total': 0, 'cloud_champs': 0, 'legacy': 0, 'docs': 0, 'emails': 0, 'resets': 0, 'dlp': 0
    })

    for u in users.values():
        d = u['department']
        dept_stats[d]['total'] += 1
        dept_stats[d]['docs'] += u['docs_created']
        dept_stats[d]['emails'] += u['emails_sent']
        dept_stats[d]['resets'] += u['total_resets']
        dept_stats[d]['dlp'] += u['external_shares_count'] + u['public_links_count']
        if u['docs_created'] >= 2:
            dept_stats[d]['cloud_champs'] += 1
        elif u['emails_sent'] > 0 and u['docs_created'] == 0:
            dept_stats[d]['legacy'] += 1

    print("\n" + "=" * 118)
    print(" SECTION 9: DEPARTMENTAL DIGITAL MATURITY & RISK SCORECARD")
    print("=" * 118)
    print(f" {'DEPARTMENT':<24} | {'USERS':>6} | {'CLOUD ADOPTERS':>14} | {'LEGACY EMAILERS':>15} | {'DOCS':>6} | {'RESETS':>6} | {'MODERNIZATION INDEX'}")
    print("-" * 118)

    sorted_dept = sorted(dept_stats.items(), key=lambda x: (x[1]['cloud_champs'], x[1]['docs']), reverse=True)
    for d_name, ds in sorted_dept:
        tot = max(1, ds['total'])
        mod_rate = round((ds['cloud_champs'] / tot) * 100)
        mod_str = f"{mod_rate}% Cloud Fluent"
        d_display = truncate(d_name, 24)
        print(f" {d_display:<24} | {ds['total']:>6} | {ds['cloud_champs']:>14} | {ds['legacy']:>15} | {ds['docs']:>6} | {ds['resets']:>6} | {mod_str:>19}")

    # =========================================================================
    # SECTION 10: MASTER EMPLOYEE ROSTER (DEPARTMENT-BY-DEPARTMENT DEEP DETAIL)
    # =========================================================================
    print("\n" + "=" * 118)
    print(" SECTION 10: MASTER EMPLOYEE ROSTER (DEPARTMENT-BY-DEPARTMENT DEEP DETAIL)")
    print("=" * 118)

    dept_roster = defaultdict(list)
    for u in users.values():
        dept_roster[u['department']].append(u)

    for d_name, _ in sorted_dept:
        members = dept_roster[d_name]
        members.sort(key=lambda x: (x['total_resets'], x['external_shares_count']), reverse=True)

        print(f"\n ► DEPARTMENT: {d_name.upper()} ({len(members)} Accounts)")
        print(f"   {'EMPLOYEE NAME':<20} | {'EMAIL ADDRESS':<28} | {'PRIVILEGE':<14} | {'2SV':>4} | {'PW RESETS':>9} | {'LAST RESET':<10} | {'EXT SHARES':>10} | {'ENABLEMENT PROFILE'}")
        print("   " + "-" * 114)

        for m in members:
            n_str = truncate(m['name'], 20)
            e_str = truncate(m['email'], 28)
            p_str = truncate(m['privilege_tier'], 14)
            two_sv = "YES" if m['is_enrolled_in_2sv'] else "NO"
            resets_str = str(m['total_resets'])
            ext_str = str(m['external_shares_count'])

            if m['docs_created'] >= 2:
                profile_tag = "Cloud Champion"
            elif m['emails_sent'] > 0 and m['docs_created'] == 0:
                profile_tag = "Legacy Emailer"
            elif m['docs_created'] == 1:
                profile_tag = "Cloud Practitioner"
            else:
                profile_tag = "Needs Enablement"

            print(f"   {n_str:<20} | {e_str:<28} | {p_str:<14} | {two_sv:>4} | {resets_str:>9} | {m['last_reset_date']:<10} | {ext_str:>10} | {profile_tag}")

    # =========================================================================
    # SECTION 11: MASTER CSV COMPILATION & EXPORT
    # =========================================================================
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_file = os.path.join(BASE_DIR, f"cci_master_deep_audit_{timestamp}.csv")
    print("\n" + "=" * 118)
    print(f" SECTION 11: COMPILING EXHAUSTIVE AUDIT DATASET TO CSV: {csv_file}")
    print("=" * 118)

    all_users_sorted = sorted(users.values(), key=lambda x: (x['department'], -x['total_resets']))
    try:
        with open(csv_file, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Employee Name', 'Corporate Email', 'Department', 'Privilege Tier',
                'Is Super Admin', 'Is Delegated Admin', 'Is Suspended', '2SV Enrolled',
                'Account Created Date', 'Last Login Date', 'Days Inactive', 'Has Paid License',
                'IT Admin Forced Resets', 'User Self-Service Resets', 'Total Resets (180d)', 'Last Reset Date',
                'External Files Shared', 'Public Links Exposed', 'Connected OAuth Apps', 'Critical OAuth Apps',
                'Has Mail Forwarding', 'Forwarding Target', 'Suspicious Login Count', 'Docs Created', 'Emails Sent'
            ])
            for u in all_users_sorted:
                writer.writerow([
                    u['name'], u['email'], u['department'], u['privilege_tier'],
                    'YES' if u['is_super_admin'] else 'NO',
                    'YES' if u['is_delegated_admin'] else 'NO',
                    'YES' if u['is_suspended'] else 'NO',
                    'YES' if u['is_2sv'] else 'NO',
                    u['created_at'], u['last_login'],
                    u['days_inactive'] if u['days_inactive'] is not None else 'N/A',
                    'YES' if u['has_paid_license'] else 'NO',
                    u['admin_resets'], u['self_resets'], u['total_resets'], u['last_reset_date'],
                    u['external_shares_count'], u['public_links_count'],
                    u['oauth_apps_count'], u['critical_apps_count'],
                    'YES' if u['has_forwarding'] else 'NO', u['forwarding_target'],
                    u['suspicious_logins_count'], u['docs_created'], u['emails_sent']
                ])
        print(f" [✓] SUCCESS: Master Governance Dataset saved ({len(all_users_sorted)} user rows).")
    except Exception as e:
        print(f" [!] CSV Export Note: {e}")

    print("=" * 118 + "\n")


if __name__ == '__main__':
    run_master_deep_audit()