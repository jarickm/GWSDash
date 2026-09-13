"""
Coolaire Consolidated Inc. (CCI) - Executive Governance & Action Console
Interactive Terminal Command Center for IT Leadership & Executive Management.
Provides on-demand auditing, single-employee deep-dives, and CSV compliance exports.
Pure Read-Only: Does NOT modify any Google accounts or database records.
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
ESTIMATED_SEAT_MONTHLY_COST = float(os.environ.get('LICENSE_MONTHLY_COST', '14.40'))  # Google Workspace Business Standard default

SCOPES = [
    'https://www.googleapis.com/auth/admin.directory.user.readonly',
    'https://www.googleapis.com/auth/admin.reports.audit.readonly',
    'https://www.googleapis.com/auth/admin.reports.usage.readonly',
    'https://www.googleapis.com/auth/apps.licensing'
]

DEPARTMENT_TAXONOMY = {
    'Finance': ['finance', 'fa', 'billing', 'disbursement', 'ap', 'ar'],
    'Accounting': ['accounting', 'acct', 'bookkeeper', 'audit_acct', 'general_accounting', 'ledger'],
    'CNC & Treasury': ['cnc', 'treasury', 'cash', 'treasurer'],
    'Credit and Collection': ['credit and collection', 'credit & collection', 'collection', 'credit'],
    'Purchasing': ['purchasing', 'procurement', 'purch', 'buyer', 'sourcing'],
    'Sales': ['sales', 'commercial', 'account executive', 'business development'],
    'Service': ['service', 'technical_service', 'technician', 'maintenance', 'hvac'],
    'Production': ['production', 'manufacturing', 'plant', 'factory', 'assembly'],
    'Warehouse': ['warehouse', 'logistics', 'inventory', 'stock', 'receiving', 'storekeeper'],
    'HR': ['hr', 'human resources', 'people', 'personnel', 'admin_hr'],
    'Audit': ['audit', 'internal_audit', 'compliance'],
    'Asset': ['asset', 'facilities', 'fleet', 'machinery', 'property'],
    'Marketing': ['marketing', 'mktg', 'creatives', 'branding', 'graphics', 'digital'],
    'Imports': ['imports', 'customs', 'shipping', 'brokerage', 'importation'],
    'IT Department': ['it', 'tech', 'sysadmin', 'information technology', 'systems'],
    'Management': ['management', 'executive', 'c-level', 'board', 'director', 'president', 'ceo']
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
    words = raw_clean.split()

    for canonical_name, aliases in DEPARTMENT_TAXONOMY.items():
        if canonical_name.lower() in raw_clean:
            return canonical_name
        for alias in aliases:
            if alias in raw_clean or alias in words:
                return canonical_name

    return raw_text.strip()


class GovernanceEngine:
    def __init__(self):
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            print(f"[!] Critical Error: Key file missing at {SERVICE_ACCOUNT_FILE}")
            sys.exit(1)

        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        ).with_subject(ADMIN_EMAIL)

        self.dir_service = build('admin', 'directory_v1', credentials=creds, cache_discovery=False)
        self.rep_service = build('admin', 'reports_v1', credentials=creds, cache_discovery=False)
        self.lic_service = build('licensing', 'v1', credentials=creds, cache_discovery=False)

        self.users = {}
        self.password_events = []
        self.external_shares = []
        self.public_links = []
        self.user_usage = defaultdict(lambda: {'docs': 0, 'sheets': 0, 'emails': 0})
        self.initialized = False

    def load_data(self):
        print("\n[*] Initializing domain intelligence cache from Google Workspace...")
        now = datetime.datetime.now(datetime.timezone.utc)

        # 1. Ingest Directory
        page_token = None
        while True:
            res = self.dir_service.users().list(
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

                self.users[em] = {
                    'email': em,
                    'name': name,
                    'department': dept,
                    'privilege_tier': tier,
                    'is_super_admin': is_super,
                    'is_delegated_admin': is_delegated,
                    'is_suspended': is_susp,
                    'is_2sv': is_2sv,
                    'last_login': last_login_str[:10] if last_login_str else 'Never',
                    'days_inactive': days_inactive,
                    'has_paid_license': True,
                    'admin_resets': 0,
                    'self_resets': 0,
                    'total_resets': 0,
                    'last_reset_date': 'None',
                    'external_shares_count': 0
                }

            page_token = res.get('nextPageToken')
            if not page_token:
                break

        # 2. Ingest License Verification
        try:
            l_tok = None
            assigned = set()
            while True:
                l_res = self.lic_service.licenseAssignments().listForProduct(
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
                for em, u in self.users.items():
                    u['has_paid_license'] = (em in assigned)
        except Exception:
            pass

        # 3. Ingest Password Resets (180 Days)
        try:
            p_tok = None
            while True:
                res = self.rep_service.activities().list(
                    userKey='all', applicationName='admin', eventName='CHANGE_PASSWORD', maxResults=100, pageToken=p_tok
                ).execute(num_retries=3)
                for item in res.get('items', []):
                    admin_actor = item.get('actor', {}).get('email', '').lower().strip()
                    t_str = item.get('id', {}).get('time', '')
                    for ev in item.get('events', []):
                        pms = {p['name']: p.get('value') or p.get('stringValue') for p in ev.get('parameters', [])}
                        target_em = (pms.get('USER_EMAIL') or pms.get('TARGET_USER') or '').lower().strip()
                        if target_em in self.users:
                            u = self.users[target_em]
                            u['admin_resets'] += 1
                            u['total_resets'] += 1
                            u['last_reset_date'] = t_str[:10]
                            self.password_events.append({
                                'timestamp': t_str[:19].replace('T', ' '),
                                'user': target_em,
                                'type': 'Admin Forced Reset',
                                'actor': admin_actor
                            })
                p_tok = res.get('nextPageToken')
                if not p_tok:
                    break
        except Exception:
            pass

        try:
            p_tok = None
            while True:
                res = self.rep_service.activities().list(
                    userKey='all', applicationName='login', maxResults=100, pageToken=p_tok
                ).execute(num_retries=3)
                for item in res.get('items', []):
                    user_actor = item.get('actor', {}).get('email', '').lower().strip()
                    t_str = item.get('id', {}).get('time', '')
                    for ev in item.get('events', []):
                        ev_name = ev.get('name', '')
                        if ev_name in ['password_change', 'account_recovery_password_reset']:
                            if user_actor in self.users:
                                u = self.users[user_actor]
                                u['self_resets'] += 1
                                u['total_resets'] += 1
                                u['last_reset_date'] = t_str[:10]
                                evt_type = 'Self-Service Recovery' if ev_name == 'account_recovery_password_reset' else 'User Password Change'
                                self.password_events.append({
                                    'timestamp': t_str[:19].replace('T', ' '),
                                    'user': user_actor,
                                    'type': evt_type,
                                    'actor': user_actor
                                })
                p_tok = res.get('nextPageToken')
                if not p_tok:
                    break
        except Exception:
            pass

        # 4. Ingest DLP & External Shares
        try:
            d_tok = None
            p_count = 0
            while p_count < 6:
                d_res = self.rep_service.activities().list(
                    userKey='all', applicationName='drive', maxResults=100, pageToken=d_tok
                ).execute(num_retries=2)
                for item in d_res.get('items', []):
                    actor_em = item.get('actor', {}).get('email', '').lower().strip()
                    t_str = item.get('id', {}).get('time', '')
                    for ev in item.get('events', []):
                        pms = {p['name']: p.get('value') or p.get('stringValue') for p in ev.get('parameters', [])}
                        title = pms.get('doc_title', 'Untitled Document')
                        target_u = (pms.get('target_user') or '').lower().strip()
                        vis = pms.get('visibility', '')

                        if vis in ['people_with_link', 'public']:
                            self.public_links.append({
                                'timestamp': t_str[:19].replace('T', ' '),
                                'actor': actor_em,
                                'title': title,
                                'visibility': vis
                            })

                        if target_u and ALLOWED_DOMAIN not in target_u and '@' in target_u:
                            if actor_em in self.users:
                                self.users[actor_em]['external_shares_count'] += 1
                            self.external_shares.append({
                                'timestamp': t_str[:19].replace('T', ' '),
                                'actor': actor_em,
                                'title': title,
                                'recipient': target_u,
                                'recipient_domain': target_u.split('@')[-1]
                            })
                d_tok = d_res.get('nextPageToken')
                p_count += 1
                if not d_tok:
                    break
        except Exception:
            pass

        # 5. Ingest Digital Maturity
        for days_back in range(3, 10):
            test_date = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()
            try:
                u_res = self.rep_service.userUsageReport().get(
                    userKey='all', date=test_date,
                    parameters='drive:num_google_documents_created,drive:num_google_spreadsheets_created,gmail:num_emails_sent'
                ).execute(num_retries=2)
                for r in u_res.get('usageReports', []):
                    em = r.get('entity', {}).get('userEmail', '').lower().strip()
                    pms = {p['name']: p for p in r.get('parameters', [])}
                    self.user_usage[em]['docs'] = int(pms.get('drive:num_google_documents_created', {}).get('intValue', 0))
                    self.user_usage[em]['sheets'] = int(pms.get('drive:num_google_spreadsheets_created', {}).get('intValue', 0))
                    self.user_usage[em]['emails'] = int(pms.get('gmail:num_emails_sent', {}).get('intValue', 0))
                break
            except Exception:
                continue

        self.initialized = True
        print(f"[✓] Intelligence cache ready! Audited {len(self.users)} domain accounts.")

    # -------------------------------------------------------------------------
    # MENU VIEWS
    # -------------------------------------------------------------------------
    def show_password_audit(self):
        print("\n" + "=" * 110)
        print(" AUDIT 1: USER PRIVILEGES & HABITUAL PASSWORD RESETTERS (180 DAYS)")
        print("=" * 110)
        print(f" {'EMPLOYEE NAME':<22} | {'EMAIL ADDRESS':<30} | {'DEPT':<14} | {'PRIVILEGE':<14} | {'IT':>3} | {'SELF':>4} | {'TOT':>4} | {'RISK'}")
        print("-" * 110)

        resetters = [u for u in self.users.values() if u['total_resets'] > 0 or u['is_super_admin'] or u['is_delegated_admin']]
        resetters.sort(key=lambda x: (x['total_resets'], x['admin_resets']), reverse=True)

        if not resetters:
            print(" [✓] No password resets or privileged anomalies recorded.")
        else:
            for u in resetters[:30]:
                tot = u['total_resets']
                if tot >= 4:
                    risk = "🔴 Chronic (Password Mgr)"
                elif tot >= 2:
                    risk = "🟡 Frequent (Coaching)"
                elif tot == 1:
                    risk = "🟢 Routine"
                else:
                    risk = "⚪ Admin Baseline"

                print(f" {u['name'][:22]:<22} | {u['email'][:30]:<30} | {u['department'][:14]:<14} | {u['privilege_tier'][:14]:<14} | {u['admin_resets']:>3} | {u['self_resets']:>4} | {tot:>4} | {risk}")

    def show_dlp_audit(self):
        print("\n" + "=" * 110)
        print(" AUDIT 2: EXTERNAL FILE SHARING & DLP DATA LEAKAGE")
        print("=" * 110)
        print(f" Total External Shares: {len(self.external_shares)} | Public 'Anyone with Link' Active: {len(self.public_links)}")
        print("-" * 110)
        print(f" {'TIMESTAMP':<19} | {'EMPLOYEE (OWNER)':<28} | {'DOCUMENT TITLE':<28} | {'EXTERNAL RECIPIENT'}")
        print("-" * 110)

        if not self.external_shares:
            print(" [✓] Zero external domain shares discovered.")
        else:
            for s in self.external_shares[:25]:
                owner = self.users.get(s['actor'], {}).get('name', s['actor'])
                owner_str = f"{owner[:12]} ({s['actor']})"
                print(f" {s['timestamp']:<19} | {owner_str[:28]:<28} | {s['title'][:26]:<28} | ⚠️ {s['recipient']}")

    def show_license_reclamation(self):
        print("\n" + "=" * 110)
        print(" AUDIT 3: LICENSE RECLAMATION & BUDGET RECOVERY PIPELINE")
        print("=" * 110)

        suspended = [u for u in self.users.values() if u['is_suspended'] and u['has_paid_license']]
        dormant = [u for u in self.users.values() if not u['is_suspended'] and u['has_paid_license'] and u['days_inactive'] is not None and u['days_inactive'] >= 60]
        never = [u for u in self.users.values() if not u['is_suspended'] and u['has_paid_license'] and u['last_login'] == 'Never']

        total_seats = len(suspended) + len(dormant) + len(never)
        annual_waste = total_seats * ESTIMATED_SEAT_MONTHLY_COST * 12

        print(f" • Immediate Reclaim Seats (Suspended):  {len(suspended)} seats")
        print(f" • Dormant Seats (>60 Days Inactive):    {len(dormant)} seats")
        print(f" • Never Logged In Seats:                {len(never)} seats")
        print(f" • Total Recoverable Seat Pool:          {total_seats} seats")
        print(f" • Direct Annual Budget Recovery:        ${annual_waste:,.2f} USD/year")
        print("-" * 110)
        print(f" {'EMPLOYEE NAME':<22} | {'EMAIL ADDRESS':<32} | {'DEPT':<15} | {'INACTIVITY':<18} | {'RECOMMENDED ACTION'}")
        print("-" * 110)

        for u in suspended:
            print(f" {u['name'][:22]:<22} | {u['email'][:32]:<32} | {u['department'][:15]:<15} | {'SUSPENDED':<18} | 🔴 REVOKE SEAT NOW")
        for u in never[:10]:
            print(f" {u['name'][:22]:<22} | {u['email'][:32]:<32} | {u['department'][:15]:<15} | {'NEVER LOGGED IN':<18} | 🟡 ONBOARDING FAILURE")
        for u in dormant[:15]:
            days_str = f"{u['days_inactive']} days inactive"
            print(f" {u['name'][:22]:<22} | {u['email'][:32]:<32} | {u['department'][:15]:<15} | {days_str:<18} | 🟡 HR AUDIT / RECLAIM")

    def show_cloud_maturity(self):
        print("\n" + "=" * 110)
        print(" AUDIT 4: DEPARTMENTAL CLOUD MATURITY & MODERNIZATION SCORECARD")
        print("=" * 110)

        dept_tally = defaultdict(lambda: {'total': 0, 'cloud_champs': 0, 'legacy': 0, 'docs': 0})
        for em, u in self.users.items():
            if u['is_suspended']:
                continue
            act = self.user_usage[em]
            docs = act['docs'] + act['sheets']
            d = u['department']
            dept_tally[d]['total'] += 1
            dept_tally[d]['docs'] += docs
            if docs >= 2:
                dept_tally[d]['cloud_champs'] += 1
            elif act['emails'] > 0 and docs == 0:
                dept_tally[d]['legacy'] += 1

        print(f" {'DEPARTMENT':<24} | {'USERS':>6} | {'CLOUD ADOPTERS':>14} | {'LEGACY EMAILERS':>15} | {'TOTAL DOCS':>10} | {'MODERNIZATION INDEX'}")
        print("-" * 110)

        sorted_dept = sorted(dept_tally.items(), key=lambda x: (x[1]['cloud_champs'], x[1]['docs']), reverse=True)
        for d_name, s in sorted_dept:
            tot = max(1, s['total'])
            rate = round((s['cloud_champs'] / tot) * 100)
            modern_str = f"{rate}% Modernized"
            print(f" {d_name:<24} | {s['total']:>6} | {s['cloud_champs']:>14} | {s['legacy']:>15} | {s['docs']:>10} | {modern_str:>19}")

    def inspect_single_user(self):
        print("\n" + "-" * 80)
        target = input(" Enter Employee Email to Inspect (e.g. employee@coolaireconsolidated.com): ").strip().lower()
        print("-" * 80)

        if target not in self.users:
            print(f" [!] User '{target}' not found in active Google Workspace directory.")
            return

        u = self.users[target]
        act = self.user_usage[target]
        docs = act['docs'] + act['sheets']
        last_login_display = f"{u['last_login']} ({u['days_inactive']} days ago)" if u['days_inactive'] is not None else u['last_login']

        print(f"\n ================= 360° EMPLOYEE GOVERNANCE DOSSIER =================")
        print(f" • Employee Full Name:        {u['name']}")
        print(f" • Corporate Email:           {u['email']}")
        print(f" • Assigned Department:       {u['department']}")
        print(f" • Privilege Tier:            {u['privilege_tier']}")
        print(f" • Account Active Status:     {'Suspended' if u['is_suspended'] else 'Active'}")
        print(f" • 2-Step Verification (2SV): {'Enrolled & Enforced' if u['is_2sv'] else 'MISSING (Security Risk)'}")
        print(f" • Last Recorded Login:       {last_login_display}")
        print(f" --------------------------------------------------------------------")
        print(f" • Password Resets (180 Days): {u['total_resets']} total ({u['admin_resets']} IT-Assisted | {u['self_resets']} Self-Service)")
        print(f" • Last Password Reset Date:  {u['last_reset_date']}")
        print(f" • External Files Shared:     {u['external_shares_count']} file(s) shared outside domain")
        print(f" • Cloud Velocity (Docs):     {docs} collaborative documents created")
        print(f" • Email Volume:              {act['emails']} sent emails")
        print(f" ====================================================================\n")

    def export_compliance_bundle(self):
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_file = os.path.join(BASE_DIR, f"cci_executive_governance_master_{timestamp}.csv")

        print(f"\n[*] Compiling full compliance bundle into CSV: {csv_file}")
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Employee Name', 'Corporate Email', 'Department', 'Privilege Tier',
                'Is Suspended', '2SV Enrolled', 'Last Login Date', 'Days Inactive',
                'Admin Forced Resets', 'Self Service Resets', 'Total Resets', 'Last Reset Date',
                'External Files Shared', 'Docs & Sheets Created', 'Emails Sent'
            ])

            for u in self.users.values():
                act = self.user_usage[u['email']]
                days_inact_val = u['days_inactive'] if u['days_inactive'] is not None else 'N/A'
                writer.writerow([
                    u['name'], u['email'], u['department'], u['privilege_tier'],
                    'YES' if u['is_suspended'] else 'NO',
                    'YES' if u['is_2sv'] else 'NO',
                    u['last_login'], days_inact_val,
                    u['admin_resets'], u['self_resets'], u['total_resets'], u['last_reset_date'],
                    u['external_shares_count'], act['docs'] + act['sheets'], act['emails']
                ])

        print(f" [✓] SUCCESS: Master Governance Export saved with {len(self.users)} records.")


def run_interactive_console():
    engine = GovernanceEngine()
    engine.load_data()

    while True:
        print("\n" + "=" * 70)
        print(" COOLAIRE CONSOLIDATED INC. - WORKSPACE GOVERNANCE CONSOLE")
        print("=" * 70)
        print(" [1] Audit: User Privileges & Habitual Password Resetters")
        print(" [2] Audit: External File Sharing & Public DLP Exposure")
        print(" [3] Audit: License Reclamation Pipeline & Financial Waste")
        print(" [4] Audit: Departmental Cloud Maturity & Modernization Index")
        print(" [5] Action: Single Employee 360° Governance Deep-Dive")
        print(" [6] Action: Export Master Compliance CSV Bundle")
        print(" [7] Reload Intelligence Cache from Google APIs")
        print(" [0] Exit Console")
        print("=" * 70)

        choice = input(" Enter Selection [0-7]: ").strip()

        if choice == '1':
            engine.show_password_audit()
        elif choice == '2':
            engine.show_dlp_audit()
        elif choice == '3':
            engine.show_license_reclamation()
        elif choice == '4':
            engine.show_cloud_maturity()
        elif choice == '5':
            engine.inspect_single_user()
        elif choice == '6':
            engine.export_compliance_bundle()
        elif choice == '7':
            engine.load_data()
        elif choice == '0':
            print("\n Exiting Governance Console. Goodbye!\n")
            break
        else:
            print(" [!] Invalid option. Please enter a number from 0 to 7.")


if __name__ == '__main__':
    run_interactive_console()