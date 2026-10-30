"""Shared styling for printable pages."""
import html
from datetime import date, datetime

CSS = """
* { box-sizing: border-box; }
body { font-family: Manrope, system-ui, sans-serif; color: #0B1411; margin: 0; background: #E8F1EC; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { max-width: 780px; margin: 28px auto; background: #F6FAF7; border-radius: 28px; padding: 40px 44px; }
.page.narrow { max-width: 520px; }
header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; background: #0B1411; color: #E8F1EC; border-radius: 22px; padding: 22px 26px; }
header h1 { margin: 0; font-size: 22px; font-weight: 800; letter-spacing: -.01em; }
header .lime { color: #B6F36B; }
header small { color: #9FB1A9; font-size: 12.5px; font-weight: 600; display: block; margin-top: 4px; }
header .r { text-align: right; }
header .r b { font-size: 16px; }
h2 { font-size: 11px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; color: #6B7C75; margin: 30px 0 10px; }
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 14.5px; }
th { text-align: left; font-size: 10.5px; letter-spacing: .08em; text-transform: uppercase; color: #6B7C75; padding: 0 14px 8px; }
td { padding: 12px 14px; }
td.r, th.r { text-align: right; }
tr:nth-child(even) td { background: #E8F1EC; }
tr:nth-child(even) td:first-child { border-radius: 12px 0 0 12px; } tr:nth-child(even) td:last-child { border-radius: 0 12px 12px 0; }
.total { display: flex; justify-content: space-between; align-items: center; background: #0B1411; color: #E8F1EC; border-radius: 18px; padding: 16px 22px; margin-top: 18px; }
.total b { font-size: 24px; color: #B6F36B; }
.total small { color: #9FB1A9; font-weight: 600; font-size: 13px; }
footer { display: flex; justify-content: space-between; align-items: flex-end; margin-top: 44px; gap: 24px; }
footer .s { color: #6B7C75; font-size: 13px; font-weight: 600; }
footer .sign { width: 210px; text-align: center; font-size: 12px; color: #6B7C75; font-weight: 600; padding-top: 44px; background: linear-gradient(#0B1411, #0B1411) bottom 22px center / 100% 1.5px no-repeat; }
.msg { max-width: 460px; margin: 18vh auto; background: #F6FAF7; border-radius: 28px; padding: 36px; text-align: center; }
.msg b { display: block; font-size: 20px; margin-bottom: 6px; } .msg span { color: #6B7C75; font-weight: 600; }
@media print { body { background: #fff; } .page { margin: 0; padding: 14mm; background: #fff; border-radius: 0; max-width: none; } }
"""


def page(title: str, body: str, auto: bool = False, size: str = "A4", narrow: bool = False) -> str:
    return (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>'
            '<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&display=swap" rel="stylesheet">'
            f'<style>@page {{ size: {size}; margin: 0; }}{CSS}</style>'
            f'<div class="page{" narrow" if narrow else ""}">{body}</div>'
            + ('<script>onload=()=>setTimeout(print,300)</script>' if auto else ""))


def message(title: str, text: str) -> str:
    return (f'<!doctype html><meta charset="utf-8"><title>{html.escape(title)}</title>'
            '<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&display=swap" rel="stylesheet">'
            f'<style>{CSS}</style><div class="msg"><b>{html.escape(title)}</b><span>{html.escape(text)}</span></div>')


def day(d: str) -> str:
    x = date.fromisoformat(d[:10])
    return f"{x.day} {x.strftime('%b %Y')}"


def stamp(ts: str) -> str:
    x = datetime.fromisoformat(ts)
    return f"{x.day} {x.strftime('%b %Y')}, {x.hour % 12 or 12}:{x.minute:02d} {'am' if x.hour < 12 else 'pm'}"
