"""
Coolaire Consolidated Inc. (CCI) - Shadow IT & Mailbox Exfiltration Audit Console
Audits Security Blindspots across Google Workspace:
1. Third-Party OAuth App Grants (Shadow IT reading Gmail/Drive)
2. Mailbox Auto-Forwarding Rules (Exfiltration to personal emails)
3. Threat Telemetry (Suspicious logins & anomalous authentications)
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

# Uses strictly authorized scopes already whitelisted in your domain
SCOPES = [
    'https://www.googleapis.com/auth/admin.directory.user.readonly',
    'https://www.googleapis.com/auth/admin.reports.audit.readonly'
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


class SecurityBlindspotEngine:
    def __init__(self):
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            print(f"[!] Missing service account key file: {SERVICE_ACCOUNT_FILE}")
            sys.exit(1)

        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        ).with_subject(ADMIN_EMAIL)

        self.dir_service = build('admin', 'directory_v1', credentials=creds, cache_discovery=False)
        self.rep_service = build('admin', 'reports_v1', credentials=creds, cache_discovery=False)

        self.users = {}
        self.third_party_apps = []
        self.forwarding_events = []
        self.suspicious_logins = []

    def load_cache(self):
        print("\n" + "=" * 115)
        print(" COOLAIRE CONSOLIDATED INC. - SHADOW IT & MAIL EXFILTRATION DETECTOR")
        print(f" Target Domain: @{ALLOWED_DOMAIN} | Admin: {ADMIN_EMAIL}")
        print("=" * 115)

        # 1. Ingest Directory
        print("[1/4] Loading active corporate users from Google Directory...")
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

                self.users[em] = {
                    'name': name,
                    'department': match_department(raw_dept, em),
                    'is_suspended': bool(u.get('suspended', False)),
                    'is_2sv': bool(u.get('isEnrolledIn2Sv', False)),
                    'app_grants_count': 0,
                    'critical_app_count': 0,
                    'has_forwarding': False,
                    'suspicious_login_count': 0
                }

            page_token = res.get('nextPageToken')
            if not page_token:
                break
        print(f"    -> Cached {len(self.users)} domain accounts.")

        # 2. Audit OAuth App Grants (Shadow IT)
        print("[2/4] Traversing Token Audit Log for Third-Party OAuth Grants (Shadow IT)...")
        t_tok = None
        pages = 0
        while pages < 10:
            try:
                res = self.rep_service.activities().list(
                    userKey='all', applicationName='token', maxResults=100, pageToken=t_tok
                ).execute(num_retries=3)

                for item in res.get('items', []):
                    actor_em = item.get('actor', {}).get('email', '').lower().strip()
                    t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')

                    for ev in item.get('events', []):
                        if ev.get('name') == 'authorize':
                            pms = {p['name']: p for p in ev.get('parameters', [])}
                            app_name = pms.get('app_name', {}).get('value', 'External Application')
                            client_id = pms.get('client_id', {}).get('value', 'N/A')
                            scope_list = pms.get('scope_data', {}).get('multiValue', []) or pms.get('scope', {}).get('multiValue', [])

                            # Determine Risk Severity based on scopes granted
                            has_mail = any('mail.google.com' in s or 'gmail' in s for s in scope_list)
                            has_drive = any('auth/drive' in s for s in scope_list)
                            has_contacts = any('auth/contacts' in s for s in scope_list)

                            if has_mail or has_drive:
                                risk_tier = "🔴 CRITICAL: Full Email/Drive Read Access"
                                is_critical = True
                            elif has_contacts:
                                risk_tier = "🟡 MEDIUM: Contact Book Access"
                                is_critical = False
                            else:
                                risk_tier = "🟢 LOW: Basic Profile Sign-In"
                                is_critical = False

                            if actor_em in self.users:
                                self.users[actor_em]['app_grants_count'] += 1
                                if is_critical:
                                    self.users[actor_em]['critical_app_count'] += 1

                            self.third_party_apps.append({
                                'timestamp': t_str,
                                'user': actor_em,
                                'app_name': app_name,
                                'client_id': client_id[:25] + '...' if len(client_id) > 25 else client_id,
                                'risk_tier': risk_tier,
                                'is_critical': is_critical,
                                'scopes_count': len(scope_list)
                            })

                t_tok = res.get('nextPageToken')
                pages += 1
                if not t_tok:
                    break
            except Exception as e:
                print(f"    [!] Token audit traversal note: {e}")
                break
        print(f"    -> Discovered {len(self.third_party_apps)} third-party app authorization events.")

        # 3. Audit Mailbox Auto-Forwarding Rules (Exfiltration)
        print("[3/4] Scanning User Accounts & Admin Logs for Mailbox Auto-Forwarding...")
        # Check User Accounts audit log
        try:
            u_tok = None
            while True:
                res = self.rep_service.activities().list(
                    userKey='all', applicationName='user_accounts', maxResults=100, pageToken=u_tok
                ).execute(num_retries=2)

                for item in res.get('items', []):
                    actor_em = item.get('actor', {}).get('email', '').lower().strip()
                    t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                    for ev in item.get('events', []):
                        ev_name = ev.get('name', '')
                        if 'forward' in ev_name.lower():
                            pms = {p['name']: p for p in ev.get('parameters', [])}
                            dest_addr = pms.get('forwarding_address', {}).get('value', '') or pms.get('email_address', {}).get('value', 'External Target')

                            if actor_em in self.users:
                                self.users[actor_em]['has_forwarding'] = True

                            self.forwarding_events.append({
                                'timestamp': t_str,
                                'user': actor_em,
                                'event': ev_name,
                                'destination': dest_addr,
                                'type': 'User Self-Service Forwarding Rule'
                            })
                u_tok = res.get('nextPageToken')
                if not u_tok:
                    break
        except Exception:
            pass

        # Check Admin audit log for admin-configured forwarding
        try:
            a_tok = None
            while True:
                res = self.rep_service.activities().list(
                    userKey='all', applicationName='admin', maxResults=100, pageToken=a_tok
                ).execute(num_retries=2)

                for item in res.get('items', []):
                    t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                    for ev in item.get('events', []):
                        if 'FORWARDING' in ev.get('name', ''):
                            pms = {p['name']: p for p in ev.get('parameters', [])}
                            target_user = (pms.get('USER_EMAIL') or pms.get('TARGET_USER') or '').lower().strip()
                            dest_addr = pms.get('FORWARDING_ADDRESS', {}).get('value', 'Configured Forward')

                            if target_user in self.users:
                                self.users[target_user]['has_forwarding'] = True

                            self.forwarding_events.append({
                                'timestamp': t_str,
                                'user': target_user,
                                'event': ev.get('name'),
                                'destination': dest_addr,
                                'type': 'Admin-Configured Mail Routing'
                            })
                a_tok = res.get('nextPageToken')
                if not a_tok:
                    break
        except Exception:
            pass
        print(f"    -> Audited {len(self.forwarding_events)} mailbox forwarding configuration events.")

        # 4. Audit Suspicious Logins
        print("[4/4] Scanning Login Audit Log for Threat Telemetry & Anomalous Logins...")
        try:
            l_tok = None
            pages = 0
            while pages < 6:
                res = self.rep_service.activities().list(
                    userKey='all', applicationName='login', maxResults=100, pageToken=l_tok
                ).execute(num_retries=2)

                for item in res.get('items', []):
                    actor_em = item.get('actor', {}).get('email', '').lower().strip()
                    t_str = item.get('id', {}).get('time', '')[:19].replace('T', ' ')
                    for ev in item.get('events', []):
                        ev_name = ev.get('name', '')
                        if ev_name in ['suspicious_login', 'suspicious_login_type', 'login_challenge', 'login_failure']:
                            pms = {p['name']: p for p in ev.get('parameters', [])}
                            ip_addr = item.get('ipAddress', 'Unknown IP')
                            login_type = pms.get('login_type', {}).get('value', ev_name)

                            if actor_em in self.users:
                                self.users[actor_em]['suspicious_login_count'] += 1

                            self.suspicious_logins.append({
                                'timestamp': t_str,
                                'user': actor_em,
                                'event': ev_name,
                                'ip_address': ip_addr,
                                'detail': login_type
                            })

                l_tok = res.get('nextPageToken')
                pages += 1
                if not l_tok:
                    break
        except Exception:
            pass
        print(f"    -> Audited {len(self.suspicious_logins)} threat telemetry events.")
        print("[✓] All security blindspot intelligence cached successfully!\n")

    # -------------------------------------------------------------------------
    # DISPLAY METHODS
    # -------------------------------------------------------------------------
    def show_shadow_it(self):
        print("\n" + "=" * 115)
        print(" BLINDSPOT 1: SHADOW IT & THIRD-PARTY OAUTH APP AUTHORIZATIONS")
        print("=" * 115)
        print(f" {'TIMESTAMP (UTC)':<19} | {'EMPLOYEE':<30} | {'DEPT':<14} | {'APPLICATION NAME':<22} | {'RISK CLASSIFICATION'}")
        print("-" * 115)

        if not self.third_party_apps:
            print(" [✓] ZERO SHADOW IT GRANTS: No third-party OAuth app authorizations captured.")
        else:
            # Show critical first
            sorted_apps = sorted(self.third_party_apps, key=lambda x: (x['is_critical'], x['timestamp']), reverse=True)
            for a in sorted_apps[:30]:
                u_info = self.users.get(a['user'], {'department': 'Operations'})
                print(f" {a['timestamp']:<19} | {a['user'][:30]:<30} | {u_info['department'][:14]:<14} | {a['app_name'][:22]:<22} | {a['risk_tier']}")

    def show_forwarding_rules(self):
        print("\n" + "=" * 115)
        print(" BLINDSPOT 2: MAILBOX AUTO-FORWARDING & EXFILTRATION RULES")
        print("=" * 115)
        print(f" {'TIMESTAMP (UTC)':<19} | {'SOURCE ACCOUNT':<32} | {'FORWARDING DESTINATION':<32} | {'SETUP TYPE'}")
        print("-" * 115)

        if not self.forwarding_events:
            print(" [✓] SECURE: No email auto-forwarding or external exfiltration rules found.")
        else:
            for f in self.forwarding_events:
                dest = f['destination']
                is_ext = ALLOWED_DOMAIN not in dest and '@' in dest
                dest_display = f"⚠️ {dest}" if is_ext else dest
                print(f" {f['timestamp']:<19} | {f['user'][:32]:<32} | {dest_display[:32]:<32} | {f['type']}")

    def show_threat_logins(self):
        print("\n" + "=" * 115)
        print(" BLINDSPOT 3: ANOMALOUS & SUSPICIOUS LOGIN TELEMETRY")
        print("=" * 115)
        print(f" {'TIMESTAMP (UTC)':<19} | {'EMPLOYEE':<32} | {'EVENT TYPE':<22} | {'IP ADDRESS':<16} | {'DETAIL'}")
        print("-" * 115)

        if not self.suspicious_logins:
            print(" [✓] No suspicious authentication anomalies or brute force spikes detected.")
        else:
            for s in self.suspicious_logins[:25]:
                print(f" {s['timestamp']:<19} | {s['user'][:32]:<32} | {s['event'][:22]:<22} | {s['ip_address']:<16} | {s['detail']}")

    def show_high_risk_hotlist(self):
        print("\n" + "=" * 115)
        print(" HIGH-RISK EMPLOYEE SECURITY HOTLIST (ACCOUNTS REQUIRING IMMEDIATE IT REVIEW)")
        print("=" * 115)
        print(f" {'EMPLOYEE NAME':<22} | {'EMAIL ADDRESS':<32} | {'DEPT':<14} | {'CRITICAL APPS':>13} | {'FORWARDING':>10} | {'ANOMALIES':>9}")
        print("-" * 115)

        flagged = []
        for em, u in self.users.items():
            if u['critical_app_count'] > 0 or u['has_forwarding'] or u['suspicious_login_count'] >= 2:
                flagged.append((em, u))

        flagged.sort(key=lambda x: (x[1]['has_forwarding'], x[1]['critical_app_count'], x[1]['suspicious_login_count']), reverse=True)

        if not flagged:
            print(" [✓] ZERO HIGH-RISK ACCOUNTS: No employees currently trigger critical security blindspots.")
        else:
            for em, u in flagged[:25]:
                fwd_str = "YES ⚠️" if u['has_forwarding'] else "NO"
                print(f" {u['name'][:22]:<22} | {em[:32]:<32} | {u['department'][:14]:<14} | {u['critical_app_count']:>13} | {fwd_str:>10} | {u['suspicious_login_count']:>9}")

    def export_csv(self):
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_path = os.path.join(BASE_DIR, f"cci_security_blindspots_{timestamp}.csv")
        print(f"\n[*] Exporting security blindspots to CSV: {csv_path}")

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Record Type', 'Timestamp', 'User Email', 'Department', 'Primary Indicator / App', 'Detail / Destination', 'Risk Tier'])

            for a in self.third_party_apps:
                u_dept = self.users.get(a['user'], {}).get('department', 'Operations')
                writer.writerow(['Third-Party OAuth App', a['timestamp'], a['user'], u_dept, a['app_name'], f"Scopes: {a['scopes_count']}", a['risk_tier']])

            for fwd in self.forwarding_events:
                u_dept = self.users.get(fwd['user'], {}).get('department', 'Operations')
                writer.writerow(['Mailbox Auto-Forwarding', fwd['timestamp'], fwd['user'], u_dept, fwd['event'], fwd['destination'], 'CRITICAL: Data Exfiltration Risk'])

            for s in self.suspicious_logins:
                u_dept = self.users.get(s['user'], {}).get('department', 'Operations')
                writer.writerow(['Anomalous Login', s['timestamp'], s['user'], u_dept, s['event'], s['ip_address'], 'MEDIUM: Suspicious Login'])

        print(f" [✓] SUCCESS: CSV export saved successfully.\n")


def run_blindspot_console():
    engine = SecurityBlindspotEngine()
    engine.load_cache()

    while True:
        print("=" * 70)
        print(" CCI WORKSPACE - SHADOW IT & EXFILTRATION CONTROL CONSOLE")
        print("=" * 70)
        print(" [1] Audit: Shadow IT & Third-Party OAuth App Authorizations")
        print(" [2] Audit: Mailbox Auto-Forwarding & Exfiltration Rules")
        print(" [3] Audit: Anomalous & Suspicious Login Telemetry")
        print(" [4] View: High-Risk Employee Security Hotlist")
        print(" [5] Export: Save Full Security Blindspot Report to CSV")
        print(" [6] Refresh: Reload Audit Telemetry from Google")
        print(" [0] Exit")
        print("=" * 70)

        choice = input(" Enter Selection [0-6]: ").strip()

        if choice == '1':
            engine.show_shadow_it()
        elif choice == '2':
            engine.show_forwarding_rules()
        elif choice == '3':
            engine.show_threat_logins()
        elif choice == '4':
            engine.show_high_risk_hotlist()
        elif choice == '5':
            engine.export_csv()
        elif choice == '6':
            engine.load_cache()
        elif choice == '0':
            print("\n Exiting Security Console. Goodbye!\n")
            break
        else:
            print(" [!] Invalid selection. Please enter 0 to 6.\n")


if __name__ == '__main__':
    run_blindspot_console()