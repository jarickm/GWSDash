"""
ReportLab Automated PDF Generator for OneWorkspace Executive Report
Coolaire Consolidated Inc. (CCI)
Upgraded for SQLAlchemy + Supabase PostgreSQL
"""

import io
import datetime
from typing import Dict, Any
from sqlalchemy import text
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


def build_executive_pdf(db_engine, department_framework: Dict[str, Any]) -> io.BytesIO:
    """
    Generates a formal, board-ready Executive Adoption PDF using ReportLab Flowables.
    Queries directly from the pooled Supabase engine.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=17,
        leading=21,
        textColor=colors.HexColor('#0f172a')
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#64748b')
    )
    header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.white
    )
    cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#1e293b')
    )
    cell_bold_style = ParagraphStyle(
        'TableCellBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#0f172a')
    )

    elements = []

    # Title & Corporate Header
    elements.append(Paragraph("Coolaire Consolidated Inc. (CCI) • Executive Board Briefing", subtitle_style))
    elements.append(Paragraph("Enterprise Google Workspace Transformation & Telemetry Report", title_style))
    elements.append(Paragraph(
        f"Generated on {datetime.datetime.now().strftime('%B %d, %Y at %H:%M UTC')} • Charter §16 & §17 Compliance Scorecard",
        subtitle_style
    ))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2563eb'), spaceAfter=14))

    # Fetch aggregated department metrics from Supabase
    query = text('''
        SELECT department,
               COUNT(DISTINCT email) as users,
               SUM(docs) as docs,
               SUM(sheets) as sheets,
               SUM(forms) as forms,
               SUM(calendar_events) as calendar,
               SUM(meet_minutes) as meet_mins,
               SUM(emails) as emails,
               batch
        FROM daily_metrics
        GROUP BY department, batch
        ORDER BY (SUM(docs) + SUM(sheets) * 10 + SUM(calendar_events) * 15 + SUM(forms + emails) * 20 + SUM(meet_calls) * 25) DESC
    ''')

    with db_engine.connect() as conn:
        rows = conn.execute(query).fetchall()

    table_data = [
        [
            Paragraph("Rank", header_style),
            Paragraph("Department", header_style),
            Paragraph("Batch", header_style),
            Paragraph("Users", header_style),
            Paragraph("Docs & Sheets", header_style),
            Paragraph("Forms", header_style),
            Paragraph("Meet Mins", header_style),
            Paragraph("Gmail Sent", header_style),
            Paragraph("Charter Pts", header_style),
        ]
    ]

    total_users = 0
    total_files = 0
    total_forms = 0
    total_meet = 0
    total_emails = 0
    total_pts = 0

    for idx, r in enumerate(rows, start=1):
        dept_name = r[0] or 'Unassigned'
        users_cnt = int(r[1] or 0)
        docs_cnt = int(r[2] or 0)
        sheets_cnt = int(r[3] or 0)
        forms_cnt = int(r[4] or 0)
        cal_cnt = int(r[5] or 0)
        meet_mins = int(r[6] or 0)
        emails_cnt = int(r[7] or 0)
        batch_label = r[8] or department_framework.get(dept_name, {}).get('batch', 'General')

        pts = (docs_cnt + sheets_cnt) * 10 + (cal_cnt * 15) + (forms_cnt + emails_cnt) * 20 + (meet_mins // 10)

        total_users += users_cnt
        total_files += (docs_cnt + sheets_cnt)
        total_forms += forms_cnt
        total_meet += meet_mins
        total_emails += emails_cnt
        total_pts += pts

        table_data.append([
            Paragraph(f"#{idx}", cell_style),
            Paragraph(dept_name, cell_bold_style),
            Paragraph(batch_label, cell_style),
            Paragraph(str(users_cnt), cell_style),
            Paragraph(f"{docs_cnt + sheets_cnt:,}", cell_style),
            Paragraph(f"{forms_cnt:,}", cell_style),
            Paragraph(f"{meet_mins:,}m", cell_style),
            Paragraph(f"{emails_cnt:,}", cell_style),
            Paragraph(f"{pts:,}", cell_bold_style),
        ])

    table_data.append([
        Paragraph("TOTAL", header_style),
        Paragraph(f"{len(rows)} Operating Units", header_style),
        Paragraph("All Batches", header_style),
        Paragraph(str(total_users), header_style),
        Paragraph(f"{total_files:,}", header_style),
        Paragraph(f"{total_forms:,}", header_style),
        Paragraph(f"{total_meet:,}m", header_style),
        Paragraph(f"{total_emails:,}", header_style),
        Paragraph(f"{total_pts:,}", header_style),
    ])

    table = Table(table_data, colWidths=[30, 132, 52, 38, 70, 42, 58, 55, 63])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#1e293b')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f8fafc')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 16))

    elements.append(Paragraph(
        "<b>Charter §16 Governance Note:</b> Units falling below the 3,000 threshold point level are scheduled for "
        "guided hands-on workshops facilitated by Enterprise Architecture (Lead: Jarick Montojo).",
        subtitle_style
    ))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(
        "Coolaire Consolidated Inc. (CCI) • Enterprise OneWorkspace Intelligence • Supabase Powered",
        subtitle_style
    ))

    doc.build(elements)
    buffer.seek(0)
    return buffer