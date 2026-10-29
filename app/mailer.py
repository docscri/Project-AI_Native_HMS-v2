"""Optional email. Configure SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM to send mail;
without them, emails are skipped and admins share links by hand."""
import html
import os
import smtplib
from email.message import EmailMessage


def enabled() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def send(to: str, subject: str, body: str, html_body: str | None = None) -> bool:
    """Plain text always (every mail app shows it); the branded HTML version is added when given."""
    if not enabled():
        return False
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER", "")
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=15) as s:
            s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            s.send_message(msg)
        return True
    except Exception:
        return False


def app_url() -> str:
    return os.environ.get("APP_URL", "http://localhost:8050").rstrip("/")


def branded(clinic: str, heading: str, text: str, button: str, link: str, note: str) -> str:
    """Email in the app's look. Tables and inline styles only, so Gmail, Outlook and phones all show it the same."""
    e = html.escape
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#E8F1EC">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#E8F1EC;padding:32px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#F6FAF7;border-radius:28px;font-family:Manrope,Segoe UI,Helvetica,Arial,sans-serif;color:#0B1411">
<tr><td style="padding:28px 28px 0">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0B1411;border-radius:22px"><tr>
    <td style="padding:22px 24px;font-size:20px;font-weight:800;color:#E8F1EC">{e(clinic)}</td>
    <td align="right" style="padding:22px 24px;font-size:13px;font-weight:700;color:#B6F36B">Dictate</td></tr></table></td></tr>
<tr><td style="padding:30px 32px 6px;font-size:24px;font-weight:800;letter-spacing:-.01em">{e(heading)}</td></tr>
<tr><td style="padding:0 32px 26px;font-size:16px;line-height:1.6;color:#33443d">{e(text)}</td></tr>
<tr><td style="padding:0 32px 28px"><a href="{e(link)}" style="display:inline-block;background:#B6F36B;color:#0B1411;text-decoration:none;font-weight:800;font-size:16px;padding:15px 30px;border-radius:999px">{e(button)}</a></td></tr>
<tr><td style="padding:0 32px 30px;font-size:13px;line-height:1.6;color:#6B7C75">{e(note)}<br><a href="{e(link)}" style="color:#3f6b1f;word-break:break-all">{e(link)}</a></td></tr>
</table></td></tr></table></body></html>"""
