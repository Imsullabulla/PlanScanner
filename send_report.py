"""
Sender HTML-ugerapport via Gmail SMTP.
Bruges af GitHub Actions: python send_report.py scan_summary.json
Kræver miljøvariable: GMAIL_USERNAME, GMAIL_APP_PASSWORD
"""
import json
import os
import smtplib
import sys
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

TO_ADDRESS = "sebastian.christensen@sallinggroup.com"

# ── Badge-stilarter ────────────────────────────────────────────────────────────

PRIORITY_BADGE = {
    "høj":           ("background:#fee2e2;color:#b91c1c;", "Høj prioritet"),
    "middel":        ("background:#fef3c7;color:#92400e;", "Middel prioritet"),
    "lav":           ("background:#dcfce7;color:#166534;", "Lav prioritet"),
    "ikke relevant": ("background:#f3f4f6;color:#6b7280;", "Ikke relevant"),
}

RISK_BADGE = {
    "ingen":  ("background:#f0fdf4;color:#166534;", "Ingen risiko"),
    "lav":    ("background:#eff6ff;color:#1d4ed8;", "Lav risiko"),
    "middel": ("background:#fef3c7;color:#92400e;", "Middel risiko"),
    "høj":    ("background:#fee2e2;color:#b91c1c;", "Høj risiko"),
}

FORMAT_BADGE_STYLE = "background:#f0f7ff;color:#1d4ed8;"
ACTION_BADGE_STYLE = "background:#f3f4f6;color:#374151;"


# ── HTML-hjælpere ──────────────────────────────────────────────────────────────

def badge(text: str, style: str) -> str:
    return (
        f'<span style="display:inline-block;{style}font-size:11px;font-weight:600;'
        f'padding:2px 9px;border-radius:4px;margin-right:4px;white-space:nowrap;">'
        f'{text}</span>'
    )


def plan_card(plan: dict) -> str:
    pri_key = plan.get("prioritet", "lav").lower()
    pri_style, pri_label = PRIORITY_BADGE.get(pri_key, PRIORITY_BADGE["lav"])

    risk_key = plan.get("kannibaliseringsrisiko", "ingen").lower()
    risk_style, risk_label = RISK_BADGE.get(risk_key, RISK_BADGE["ingen"])

    formats_html = "".join(
        badge(f, FORMAT_BADGE_STYLE) for f in plan.get("format_match", [])
    )

    notion_url = plan.get("notion_url", "")
    notion_btn = (
        f'<a href="{notion_url}" style="display:inline-block;margin-top:12px;'
        f'color:#2563eb;font-size:13px;text-decoration:none;font-weight:500;">'
        f'Se i Notion &rarr;</a>'
    ) if notion_url else ""

    pdf_url = plan.get("pdf_url", "")
    pdf_btn = (
        f'&nbsp;&nbsp;<a href="{pdf_url}" style="display:inline-block;margin-top:12px;'
        f'color:#6b7280;font-size:13px;text-decoration:none;font-weight:500;">'
        f'&#128196; Lokalplan PDF</a>'
    ) if pdf_url and "null" not in pdf_url.lower() else ""

    hoering_html = ""
    if plan.get("hoering_aktiv") and plan.get("horingsfrist"):
        hoering_html = (
            f'<div style="margin-top:8px;font-size:12px;color:#92400e;">'
            f'&#9200; Høringsfrist: <strong>{plan["horingsfrist"]}</strong></div>'
        )

    aktion = plan.get("aktion", "")
    sammenfatning = plan.get("sammenfatning", "")

    return f"""
        <tr>
          <td style="padding:20px 28px;border-bottom:1px solid #f0f0ee;">
            <div style="margin-bottom:8px;">
              {badge(pri_label, pri_style)}{formats_html}
            </div>
            <div style="font-size:16px;font-weight:600;color:#1a1a1a;
                        line-height:1.3;margin-bottom:4px;">
              {plan.get("name", "Ukendt plan")}
            </div>
            <div style="font-size:13px;color:#787774;margin-bottom:10px;">
              {plan.get("kommune", "")} &nbsp;&middot;&nbsp;
              {plan.get("plantype", "")} &nbsp;&middot;&nbsp;
              {plan.get("status", "")}
            </div>
            <div style="font-size:14px;color:#37352f;line-height:1.65;
                        margin-bottom:10px;">
              {sammenfatning}
            </div>
            <div>
              {badge(risk_label, risk_style)}
              {badge(aktion, ACTION_BADGE_STYLE) if aktion else ""}
            </div>
            {hoering_html}
            {notion_btn}{pdf_btn}
          </td>
        </tr>"""


def no_plans_section(total_fetched: int, period_start: str, period_end: str) -> str:
    return f"""
        <tr>
          <td style="padding:44px 28px 40px;text-align:center;
                     border-top:1px solid #f0f0ee;">
            <div style="font-size:40px;line-height:1;margin-bottom:14px;">&#10003;</div>
            <div style="font-size:18px;font-weight:600;color:#1a1a1a;
                        margin-bottom:10px;">
              Ingen relevante lokalplaner denne uge
            </div>
            <div style="font-size:14px;color:#787774;max-width:380px;
                        margin:0 auto;line-height:1.65;">
              PlanScanner gennemgik <strong>{total_fetched}</strong> planer
              fra {period_start} til {period_end}.
              Ingen matchede Salling Groups kriterier for ny butiksetablering.
            </div>
            <div style="margin-top:20px;font-size:13px;color:#b0aca6;">
              Systemet kører igen næste mandag.
            </div>
          </td>
        </tr>"""


def build_html(summary: dict, actions_url: str) -> str:
    stats        = summary.get("stats", {})
    plans        = summary.get("relevant_plans", [])
    scan_date    = summary.get("date", date.today().isoformat())
    days_back    = summary.get("days_back", 7)
    period_start = summary.get(
        "period_start",
        (date.today() - timedelta(days=days_back)).isoformat()
    )
    period_end   = summary.get("period_end", scan_date)

    total     = stats.get("total_fetched", 0)
    analysed  = stats.get("ai_analysed", 0)
    to_notion = stats.get("notion_written", 0)
    irrelevant = stats.get("skipped_irrelevant", 0)

    notion_count_color = "#166534" if to_notion > 0 else "#1a1a1a"

    if plans:
        n = len(plans)
        section_label = (
            f'{n} relevant{"e" if n != 1 else ""} '
            f'lokalplan{"er" if n != 1 else ""} denne uge'
        )
        plans_rows = "".join(plan_card(p) for p in plans)
        content_section = f"""
        <tr>
          <td style="padding:20px 28px 4px;border-top:1px solid #f0f0ee;">
            <div style="font-size:11px;font-weight:700;color:#9b9b9b;
                        text-transform:uppercase;letter-spacing:0.07em;">
              {section_label}
            </div>
          </td>
        </tr>
        {plans_rows}"""
    else:
        content_section = no_plans_section(total, period_start, period_end)

    return f"""<!DOCTYPE html>
<html lang="da">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>PlanScanner Ugerapport</title>
</head>
<body style="margin:0;padding:0;background:#f7f6f3;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
             Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0"
       style="background:#f7f6f3;">
  <tr>
    <td align="center" style="padding:32px 16px;">

      <!-- Kortcontainer -->
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:#ffffff;
                    border-radius:8px;border:1px solid #e8e6e0;">

        <!-- Header -->
        <tr>
          <td style="background:#1a1a1a;padding:24px 28px;
                     border-radius:8px 8px 0 0;">
            <div style="color:#ffffff;font-size:20px;font-weight:700;
                        letter-spacing:-0.3px;">
              &#128203; PlanScanner
            </div>
            <div style="color:#888888;font-size:13px;margin-top:4px;">
              Ugentlig lokalplansrapport &nbsp;&middot;&nbsp; {scan_date}
            </div>
          </td>
        </tr>

        <!-- Statistik -->
        <tr>
          <td style="padding:24px 28px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td width="25%" style="text-align:center;padding:0 6px;">
                  <div style="font-size:30px;font-weight:700;
                              color:#1a1a1a;line-height:1;">
                    {total}
                  </div>
                  <div style="font-size:11px;color:#787774;margin-top:5px;
                              text-transform:uppercase;letter-spacing:0.04em;">
                    Hentet
                  </div>
                </td>
                <td width="25%" style="text-align:center;padding:0 6px;
                                       border-left:1px solid #f0f0ee;">
                  <div style="font-size:30px;font-weight:700;
                              color:#1a1a1a;line-height:1;">
                    {analysed}
                  </div>
                  <div style="font-size:11px;color:#787774;margin-top:5px;
                              text-transform:uppercase;letter-spacing:0.04em;">
                    AI&#8209;analyseret
                  </div>
                </td>
                <td width="25%" style="text-align:center;padding:0 6px;
                                       border-left:1px solid #f0f0ee;">
                  <div style="font-size:30px;font-weight:700;
                              color:{notion_count_color};line-height:1;">
                    {to_notion}
                  </div>
                  <div style="font-size:11px;color:#787774;margin-top:5px;
                              text-transform:uppercase;letter-spacing:0.04em;">
                    Til Notion
                  </div>
                </td>
                <td width="25%" style="text-align:center;padding:0 6px;
                                       border-left:1px solid #f0f0ee;">
                  <div style="font-size:30px;font-weight:700;
                              color:#1a1a1a;line-height:1;">
                    {irrelevant}
                  </div>
                  <div style="font-size:11px;color:#787774;margin-top:5px;
                              text-transform:uppercase;letter-spacing:0.04em;">
                    Irrelevante
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Plan-kort eller ingen-planer-besked -->
        {content_section}

        <!-- Footer -->
        <tr>
          <td style="padding:14px 28px;background:#f7f6f3;
                     border-top:1px solid #e8e6e0;
                     border-radius:0 0 8px 8px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="font-size:12px;color:#b0aca6;">
                  Genereret af PlanScanner &nbsp;&middot;&nbsp; Plandata.dk
                </td>
                <td style="text-align:right;font-size:12px;">
                  <a href="{actions_url}"
                     style="color:#2563eb;text-decoration:none;">
                    Se fuld log &rarr;
                  </a>
                </td>
              </tr>
            </table>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


# ── Indgang ────────────────────────────────────────────────────────────────────

def main():
    summary_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("scan_summary.json")
    actions_url  = os.environ.get("GITHUB_RUN_URL", "#")

    if summary_path.exists():
        with open(summary_path, encoding="utf-8") as f:
            summary = json.load(f)
    else:
        summary = {"date": date.today().isoformat(), "stats": {}, "relevant_plans": []}

    html_body  = build_html(summary, actions_url)
    plan_count = len(summary.get("relevant_plans", []))
    scan_date  = summary.get("date", date.today().isoformat())

    if plan_count > 0:
        subject = (
            f"PlanScanner — {plan_count} "
            f"ny{'e' if plan_count != 1 else ''} "
            f"lokalplan{'er' if plan_count != 1 else ''} · {scan_date}"
        )
    else:
        subject = f"PlanScanner — Ingen nye relevante planer · {scan_date}"

    gmail_user = os.environ["GMAIL_USERNAME"]
    gmail_pass = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["From"]    = f"PlanScanner <{gmail_user}>"
    msg["To"]      = TO_ADDRESS
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, TO_ADDRESS, msg.as_string())

    print(f"HTML-rapport sendt til {TO_ADDRESS} ({plan_count} relevante planer)")


if __name__ == "__main__":
    main()
