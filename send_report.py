"""
Sender scan-rapport som e-mail via Gmail SMTP.
Bruges af GitHub Actions: cat scan_output.txt | python send_report.py
Kræver miljøvariable: GMAIL_USERNAME, GMAIL_APP_PASSWORD
"""
import os
import smtplib
import sys
from datetime import date
from email.mime.text import MIMEText

TO_ADDRESS = "sebastian.christensen@sellinggroup.com"


def main():
    body = sys.stdin.read().strip()
    if not body:
        body = "Scan gennemført — ingen logoutput registreret."

    gmail_user = os.environ["GMAIL_USERNAME"]
    gmail_pass = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = f"PlanScanner <{gmail_user}>"
    msg["To"] = TO_ADDRESS
    msg["Subject"] = f"PlanScanner ugerapport — {date.today().isoformat()}"

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, TO_ADDRESS, msg.as_string())

    print(f"Rapport sendt til {TO_ADDRESS}")


if __name__ == "__main__":
    main()
