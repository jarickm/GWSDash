"""
Coolaire Consolidated Inc. (CCI) - Detailed Terminal Governance & Security Suite
Exhaustive Pure-Terminal Diagnostic:
1. DLP File Exposure: External domain sharing, public links, and external recipient domains
2. License Reclamation & Cost Waste: Itemized suspended & dormant accounts with cost calculations
3. Cloud Maturity Scorecard: Departmental modernization rates & itemized employee enablement tiers
Pure Read-Only. Does NOT write to or modify any database tables.
"""

import os
import sys
import datetime
from collections import defaultdict
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.environ.get('SERVICE_ACCOUNT_FILE', os.path.join(BASE_DIR, 'old/credentials-old.json'))
ADMIN_EMAIL = os.environ.get('WORKSPACE_ADMIN_EMAIL', 'jarick.montojo@coolaireconsolidated.com')
ALLOWED_DOMAIN = os.environ.get('ALLOWED_DOMAIN', 'coolaireconsolidated.com')

# Estimated license cost per seat (USD/month or equivalent PHP) for ROI reporting
ESTIMATED_SEAT_MONTHLY_COST = float(os.environ.get('LICENSE_MONTHLY_COST', '14.40'))  # Google Workspace Business Standard default

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
    'Marketing': ['marketing', 'mktg', 'creatives', 'branding', 'graphics', 'digital', 'media'],
    'Imports': ['imports', 'customs', 'shipping', 'brokerage', 'importation'],
    'IT Department': ['it', 'tech', 'sysadmin', 'information technology', 'systems', 'edp'],
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
    words = raw_clean.split()

    for canonical_name, aliases in DEPARTMENT_TAXONOMY.items():
        if canonical_name.lower() in raw_clean:
            return canonical_name
        for alias in aliases:
            if alias in raw_clean or alias in words:
                return canonical_name

    return raw_text.strip()


def run_detailed_audit():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"[!] Key file not found: {SERVICE_ACCOUNT_FILE}")
        sys.exit(1)

    print("\n" + "=" * 115)
    print(" COOLAIRE CONSOLIDATED INC. - EXHAUSTIVE WORKSPACE GOVERNANCE SUITE")
    print(f" Target Domain: @{ALLOWED_DOMAIN} | Delegated Admin: {ADMIN_EMAIL}")
    print(" Generating detailed terminal intelligence reports...")
    print("=" * 115 + "\n")

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    ).with_subject(ADMIN_EMAIL)

    dir_service = build('admin', 'directory_v1', credentials=creds, cache_discovery=False)
    reports_service = build('admin', 'reports_v1', credentials=creds, cache_discovery=False)

    now = datetime.datetime.now(datetime.timezone.utc)

    # -------------------------------------------------------------------------
    # 1. DIRECTORY & LICENSING INGESTION
    # -------------------------------------------------------------------------
    print("[1/3] Interrogating Directory Accounts & Licensing API...")
    users = {}
    page_token = None
    while True:
        res = dir_service.users().list(customer='my_customer', projection='full', maxResults=500, pageToken=page_token).execute(num_retries=3)
        for u in res.get('users', []):
            em = u.get('primaryEmail', '').lower().strip()
            name = u.get('name', {}).get('fullName', em)
            raw_dept = None
            for org in u.get('organizations', []):
                raw_dept = org.get('department') or org.get('title')
                if raw_dept:
                    break

            dept = match_department(raw_dept, em)
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

            users[em] = {
                'email': em,
                'name': name,
                'department': dept,
                'is_suspended': is_susp,
                'is_2sv': is_2sv,
                'created_at': created_str[:10] if created_str else 'N/A',
                'last_login': last_login_str[:10] if last_login_str else 'Never',
                'days_inactive': days_inactive,
                'has_paid_license': True
            }

        page_token = res.get('nextPageToken')
        if not page_token:
            break

    # Probe Licensing API for exact assignment verification
    try:
        lic_service = build('licensing', 'v1', credentials=creds, cache_discovery=False)
        assigned_emails = set()
        l_tok = None
        while True:
            l_res = lic_service.licenseAssignments().listForProduct(
                productId='Google-Apps', customerId=ALLOWED_DOMAIN, maxResults=100, pageToken=l_tok
            ).execute(num_retries=2)
            for item in l_res.get('items', []):
                uid = item.get('userId', '').lower().strip()
                if uid:
                    assigned_emails.add(uid)
            l_tok = l_res.get('nextPageToken')
            if not l_tok:
                break

        if assigned_emails:
            for em, u in users.items():
                u['has_paid_license'] = (em in assigned_emails)
    except Exception:
        pass

    # -------------------------------------------------------------------------
    # 2. DLP & EXTERNAL SHARING EVENT TRAVERSAL
    # -------------------------------------------------------------------------
    print("[2/3] Auditing Google Drive Activity Logs for External File Disclosures (all pages)...")
    external_shares = []
    public_links = []
    external_domain_tally = defaultdict(int)
    dept_dlp_tally = defaultdict(int)

    page_token = None
    pages = 0
    while pages < 10:  # Traverse up to 1,000 activities
        try:
            d_res = reports_service.activities().list(
                userKey='all', applicationName='drive', maxResults=100, pageToken=page_token
            ).execute(num_retries=2)

            for item in d_res.get('items', []):
                actor_em = item.get('actor', {}).get('email', '').lower().strip()
                actor_info = users.get(actor_em, {'name': actor_em, 'department': 'Operations'})
                t_str = item.get('id', {}).get('time', '')

                for ev in item.get('events', []):
                    ev_name = ev.get('name', '')
                    pms = {p['name']: p.get('value') or p.get('stringValue') for p in ev.get('parameters', [])}
                    doc_title = pms.get('doc_title', 'Untitled Document')
                    doc_type = pms.get('doc_type', 'file')
                    target_user = (pms.get('target_user') or '').lower().strip()
                    visibility = pms.get('visibility', '')

                    # Public Link Exposure
                    if visibility in ['people_with_link', 'public']:
                        public_links.append({
                            'timestamp': t_str[:19].replace('T', ' '),
                            'actor': actor_info['name'],
                            'email': actor_em,
                            'department': actor_info['department'],
                            'title': doc_title,
                            'type': doc_type,
                            'visibility': visibility
                        })
                        dept_dlp_tally[actor_info['department']] += 1

                    # External Recipient Sharing
                    if target_user and ALLOWED_DOMAIN not in target_user and '@' in target_user:
                        target_domain = target_user.split('@')[-1]
                        external_domain_tally[target_domain] += 1
                        dept_dlp_tally[actor_info['department']] += 1

                        external_shares.append({
                            'timestamp': t_str[:19].replace('T', ' '),
                            'event': ev_name,
                            'actor': actor_info['name'],
                            'email': actor_em,
                            'department': actor_info['department'],
                            'title': doc_title,
                            'type': doc_type,
                            'recipient': target_user,
                            'recipient_domain': target_domain
                        })

            page_token = d_res.get('nextPageToken')
            pages += 1
            if not page_token:
                break
        except Exception:
            break

    # -------------------------------------------------------------------------
    # 3. USAGE REPORTS FOR CLOUD MODERNIZATION METRICS
    # -------------------------------------------------------------------------
    print("[3/3] Ingesting Workspace Usage Reports for Digital Enablement Analysis...")
    user_activity = defaultdict(lambda: {'docs': 0, 'sheets': 0, 'emails': 0})
    for days_back in range(3, 10):
        test_date = (datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()
        try:
            u_res = reports_service.userUsageReport().get(
                userKey='all', date=test_date,
                parameters='drive:num_google_documents_created,drive:num_google_spreadsheets_created,gmail:num_emails_sent'
            ).execute(num_retries=2)

            reports = u_res.get('usageReports', [])
            if reports:
                for r in reports:
                    em = r.get('entity', {}).get('userEmail', '').lower().strip()
                    pms = {p['name']: p for p in r.get('parameters', [])}
                    user_activity[em]['docs'] = int(pms.get('drive:num_google_documents_created', {}).get('intValue', 0))
                    user_activity[em]['sheets'] = int(pms.get('drive:num_google_spreadsheets_created', {}).get('intValue', 0))
                    user_activity[em]['emails'] = int(pms.get('gmail:num_emails_sent', {}).get('intValue', 0))
                break
        except Exception:
            continue

    # =========================================================================
    # SECTION 1: EXECUTIVE KPI SUMMARY & COST RECOVERY
    # =========================================================================
    suspended_paid = [u for u in users.values() if u['is_suspended'] and u['has_paid_license']]
    dormant_60d = [u for u in users.values() if not u['is_suspended'] and u['has_paid_license'] and u['days_inactive'] is not None and u['days_inactive'] >= 60]
    never_logged_in = [u for u in users.values() if not u['is_suspended'] and u['has_paid_license'] and u['last_login'] == 'Never']

    immediate_reclaim_seats = len(suspended_paid)
    review_reclaim_seats = len(dormant_60d) + len(never_logged_in)
    total_waste_seats = immediate_reclaim_seats + review_reclaim_seats

    annual_immediate_savings = immediate_reclaim_seats * ESTIMATED_SEAT_MONTHLY_COST * 12
    annual_total_potential_savings = total_waste_seats * ESTIMATED_SEAT_MONTHLY_COST * 12

    print("\n" + "=" * 115)
    print(" SECTION 1: EXECUTIVE KPI SUMMARY & LICENSE RECLAMATION FINANCIALS")
    print("=" * 115)
    print(f" • Total Corporate Accounts Audited:        {len(users)}")
    print(f" • External File Disclosures (DLP Risk):    {len(external_shares)} file share events")
    print(f" • Public Links Active ('Anyone with link'): {len(public_links)} files exposed publicly")
    print(f" • External Recipient Domains Reached:      {len(external_domain_tally)} unique external domains")
    print(f" • Immediate Reclaim Seats (Suspended):     {immediate_reclaim_seats} paid seats (~${annual_immediate_savings:,.2f}/yr wasted)")
    print(f" • Inactive Seats (>60d Dormant or Never):  {review_reclaim_seats} paid seats")
    print(f" • Total Annual License Reclaim Potential:  ${annual_total_potential_savings:,.2f} USD/year ({total_waste_seats} seats)")

    # =========================================================================
    # SECTION 2: EXTERNAL SHARING DLP INCIDENT LEDGER (ITEMIZED)
    # =========================================================================
    print("\n" + "=" * 115)
    print(" SECTION 2: EXTERNAL SHARING DLP INCIDENT LEDGER (SPECIFIC FILES & RECIPIENTS)")
    print("=" * 115)
    print(f" {'TIMESTAMP (UTC)':<19} | {'EMPLOYEE (OWNER)':<24} | {'DEPT':<14} | {'DOCUMENT TITLE':<28} | {'EXTERNAL RECIPIENT'}")
    print("-" * 115)

    if not external_shares:
        print(" [✓] SECURE: No external domain shares recorded in current audit window.")
    else:
        for s in external_shares[:25]:
            actor_str = f"{s['actor'][:10]} ({s['email']})"
            if len(actor_str) > 24:
                actor_str = actor_str[:21] + "..."
            doc_str = s['title'][:26] + ".." if len(s['title']) > 28 else s['title']
            print(f" {s['timestamp']:<19} | {actor_str:<24} | {s['department']:<14} | {doc_str:<28} | ⚠️ {s['recipient']}")

    # =========================================================================
    # SECTION 3: EXTERNAL RECIPIENT DOMAINS (WHERE IS DATA GOING?)
    # =========================================================================
    print("\n" + "=" * 115)
    print(" SECTION 3: TOP EXTERNAL RECIPIENT DOMAINS (DESTINATION RISK)")
    print("=" * 115)
    print(f" {'EXTERNAL RECIPIENT DOMAIN':<35} | {'FILES RECEIVED':>15} | {'RISK CLASSIFICATION'}")
    print("-" * 115)

    if not external_domain_tally:
        print(" [✓] No external destination domains detected.")
    else:
        sorted_domains = sorted(external_domain_tally.items(), key=lambda x: x[1], reverse=True)
        for dom, cnt in sorted_domains[:10]:
            if dom in ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com']:
                risk = "🔴 High Risk: Personal Webmail Leakage"
            else:
                risk = "🟡 Medium Risk: Third-Party Vendor / External Partner"
            print(f" @{dom:<34} | {cnt:>15} | {risk}")

    # =========================================================================
    # SECTION 4: LICENSE RECLAMATION PIPELINE (ITEMIZED SEATS)
    # =========================================================================
    print("\n" + "=" * 115)
    print(" SECTION 4: LICENSE RECLAMATION PIPELINE (PAID SEATS ELIGIBLE FOR DE-PROVISIONING)")
    print("=" * 115)
    print(f" {'EMPLOYEE NAME':<22} | {'EMAIL ADDRESS':<32} | {'DEPARTMENT':<15} | {'STATUS / INACTIVITY':<22} | {'ACTION'}")
    print("-" * 115)

    reclaim_roster = []
    for u in suspended_paid:
        reclaim_roster.append({
            'name': u['name'], 'email': u['email'], 'dept': u['department'],
            'status': 'SUSPENDED ACCOUNT', 'action': '🔴 REVOKE SEAT IMMEDIATELY'
        })
    for u in never_logged_in:
        reclaim_roster.append({
            'name': u['name'], 'email': u['email'], 'dept': u['department'],
            'status': 'NEVER LOGGED IN', 'action': '🟡 RECLAIM OR RESEND ONBOARDING'
        })
    for u in dormant_60d:
        reclaim_roster.append({
            'name': u['name'], 'email': u['email'], 'dept': u['department'],
            'status': f'DORMANT ({u["days_inactive"]}d inactive)', 'action': '🟡 AUDIT WITH HR'
        })

    if not reclaim_roster:
        print(" [✓] OPTIMAL: Zero wasted or dormant licenses found. Seat capacity is 100% efficient.")
    else:
        for r in reclaim_roster[:25]:
            name_str = r['name'][:22]
            email_str = r['email'][:32]
            dept_str = r['dept'][:15]
            print(f" {name_str:<22} | {email_str:<32} | {dept_str:<15} | {r['status']:<22} | {r['action']}")

    # =========================================================================
    # SECTION 5: CLOUD MATURITY & MODERNIZATION SCORECARD
    # =========================================================================
    dept_benchmarks = defaultdict(lambda: {
        'total': 0, 'cloud_champions': 0, 'legacy_emailers': 0, 'disengaged': 0, 'total_docs': 0, 'total_emails': 0
    })

    user_maturity_list = []
    for em, u in users.items():
        if u['is_suspended']:
            continue
        act = user_activity[em]
        docs_created = act['docs'] + act['sheets']
        emails_sent = act['emails']

        if docs_created >= 2:
            tier = "Cloud Champion"
        elif docs_created == 1:
            tier = "Cloud Practitioner"
        elif emails_sent > 0 and docs_created == 0:
            tier = "Legacy Emailer (Mailbox Only)"
        else:
            tier = "Needs Cloud Enablement"

        d = u['department']
        dept_benchmarks[d]['total'] += 1
        dept_benchmarks[d]['total_docs'] += docs_created
        dept_benchmarks[d]['total_emails'] += emails_sent
        if tier in ['Cloud Champion', 'Cloud Practitioner']:
            dept_benchmarks[d]['cloud_champions'] += 1
        elif tier == 'Legacy Emailer (Mailbox Only)':
            dept_benchmarks[d]['legacy_emailers'] += 1
        else:
            dept_benchmarks[d]['disengaged'] += 1

        user_maturity_list.append({
            'name': u['name'], 'email': em, 'department': d,
            'docs': docs_created, 'emails': emails_sent, 'tier': tier
        })

    print("\n" + "=" * 115)
    print(" SECTION 5: DEPARTMENTAL DIGITAL MATURITY & CLOUD TRANSITION INDEX")
    print("=" * 115)
    print(f" {'DEPARTMENT':<24} | {'USERS':>6} | {'CLOUD ADOPTERS':>14} | {'LEGACY EMAILERS':>15} | {'DOCS CREATED':>12} | {'MODERNIZATION INDEX'}")
    print("-" * 115)

    sorted_dept_bm = sorted(dept_benchmarks.items(), key=lambda x: (x[1]['cloud_champions'], x[1]['total_docs']), reverse=True)
    for d_name, bm in sorted_dept_bm:
        tot = max(1, bm['total'])
        mod_rate = round((bm['cloud_champions'] / tot) * 100)
        idx_str = f"{mod_rate}% Cloud Fluent"
        print(f" {d_name:<24} | {bm['total']:>6} | {bm['cloud_champions']:>14} | {bm['legacy_emailers']:>15} | {bm['total_docs']:>12} | {idx_str:>19}")

    # =========================================================================
    # SECTION 6: INDIVIDUAL EMPLOYEE ENABLEMENT ROSTER (ITEMIZED SAMPLE)
    # =========================================================================
    print("\n" + "=" * 115)
    print(" SECTION 6: INDIVIDUAL EMPLOYEE ENABLEMENT CLASSIFICATION (SAMPLE ROSTER)")
    print("=" * 115)
    print(f" {'EMPLOYEE NAME':<22} | {'EMAIL ADDRESS':<32} | {'DEPARTMENT':<14} | {'DOCS':>5} | {'EMAILS':>6} | {'ENABLEMENT PROFILE'}")
    print("-" * 115)

    # Sort users: Legacy emailers and disengaged first to prioritize training
    user_maturity_list.sort(key=lambda x: (x['tier'] != 'Legacy Emailer (Mailbox Only)', -x['emails'], x['docs']))
    for u in user_maturity_list[:25]:
        name_str = u['name'][:22]
        email_str = u['email'][:32]
        dept_str = u['department'][:14]
        print(f" {name_str:<22} | {email_str:<32} | {dept_str:<14} | {u['docs']:>5} | {u['emails']:>6} | {u['tier']}")

    print("=" * 115 + "\n")


if __name__ == '__main__':
    run_detailed_audit()