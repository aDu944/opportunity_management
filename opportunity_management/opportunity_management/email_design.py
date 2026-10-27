"""ALKHORA's notification email design system.

One place for the shape every business email shares, so eighteen templates do not
become eighteen copies of inline HTML. The rules it encodes (Ahmed, 2026-10-25):

* A 4px rule in the department colour for an ordinary event; a SOLID band only for a
  deadline or a welcome, so the band keeps meaning something.
* Mono eyebrow naming the event, then the thing itself as the headline. One figure may
  be set large, and only when that figure is the point of the email.
* Four or five label/value rows, never more. Labels are bilingual and every cell that
  can hold a name carries dir="auto", because most customers and all staff names here
  are Arabic.
* One primary action, named for what it opens. A second action only where the reader
  has a genuine decision (approve / reject).
* Graphics are drawn with table cells. Outlook renders through Word and strips inline
  SVG; Outlook and Gmail block remote images by default. A picture would often arrive
  as an empty frame, so there are no pictures.
* Everything is inline styles in a 600px table. No <style> block: Gmail strips it.
"""

import html

# Department accents. SYS doubles as the brand blue for anything with no department.
QTN = "#296acc"     # quotations, sales
LOG = "#1f6f6a"     # receipts, shipments
ACC = "#5b4b8a"     # accounts, journals
HR = "#2f6f45"      # leave, attendance
SYS = "#44546a"     # accounts, onboarding
BRAND = "#296acc"
URGENT = "#a01b14"  # today / overdue
AMBER = "#c8860d"   # recorded, no action needed

INK = "#14181f"
MUTED = "#5a6472"
FAINT = "#8b94a3"
HAIR = "#eef0f4"
RULE_SOFT = "#d8dde6"   # a touch stronger, for a table head underline

_SANS = "'IBM Plex Sans',Segoe UI,Arial,sans-serif"
_MONO = "'IBM Plex Mono',Consolas,monospace"
_AR = "'IBM Plex Sans Arabic',Segoe UI,Arial,sans-serif"

COMPANY = "ALKHORA for General Trading — AL KHORA"


def esc(value) -> str:
    """Escape anything going into the HTML. Customer names carry & and < often enough."""
    return html.escape("" if value is None else str(value), quote=True)


def _ar(text: str) -> str:
    """An Arabic fragment in its own face, so Outlook does not fall back to a serif."""
    return f'<span style="font-family:{_AR}">{esc(text)}</span>'


def label(en: str, ar: str = "") -> str:
    return esc(en) + (f" · {_ar(ar)}" if ar else "")


def money(amount, currency) -> str:
    """7,500 USD. Never a bare number: half these documents are not in dinars."""
    try:
        return f"{esc(currency or '')} {float(amount or 0):,.0f}".strip()
    except (TypeError, ValueError):
        return esc(currency or "")


def name_cell(value, mono: bool = False) -> str:
    """A value that may be Arabic, Latin or both. dir=auto lets the client decide."""
    face = _MONO if mono else _AR
    return f'<span style="font-family:{face}" dir="auto">{esc(value)}</span>'


def link(text, href, accent=BRAND, mono: bool = False) -> str:
    face = _MONO if mono else _SANS
    return (f'<a href="{esc(href)}" style="font-family:{face};color:{accent};'
            f'text-decoration:none;font-weight:500">{esc(text)}</a>')


def row(lbl: str, value_html: str) -> str:
    """One label/value line. value_html is TRUSTED - escape before passing it."""
    # text-align:left on both cells: dir="auto" inside sets the base direction for the
    # bidi algorithm, which is what we want, but it also flips the block's alignment, so
    # an Arabic name would shunt its row to the right and break the column.
    return (
        f'<tr><td style="padding:7px 0;color:{MUTED};width:44%;border-top:1px solid {HAIR};'
        f'vertical-align:top;font-size:13.5px;text-align:left">{lbl}</td>'
        f'<td style="padding:7px 0;color:{INK};border-top:1px solid {HAIR};font-size:13.5px;'
        f'text-align:left">{value_html}</td></tr>'
    )


def button(text, href, accent=BRAND, outline: bool = False, ar: str = "") -> dict:
    return {"text": text, "href": href, "accent": accent, "outline": outline, "ar": ar}


def _button_cell(b: dict) -> str:
    inner = esc(b["text"]) + (f" · {_ar(b['ar'])}" if b.get("ar") else "")
    if b.get("outline"):
        return (f'<td style="background:#ffffff;border:1px solid {b["accent"]};border-radius:5px">'
                f'<a href="{esc(b["href"])}" style="display:inline-block;padding:11px 25px;'
                f'font-size:14px;font-weight:600;color:{b["accent"]};text-decoration:none">'
                f'{inner}</a></td>')
    return (f'<td style="background:{b["accent"]};border-radius:5px">'
            f'<a href="{esc(b["href"])}" style="display:inline-block;padding:12px 26px;'
            f'font-size:14px;font-weight:600;color:#ffffff;text-decoration:none">'
            f'{inner}</a></td>')


def progress(stations, accent) -> str:
    """A reached/unreached bar drawn as table cells - Ordered / Received / Invoiced.

    stations: [(caption, reached_bool), ...]. Built from cells because this is the only
    kind of graphic that survives Outlook with the colours intact.
    """
    n = len(stations)
    pct = max(1, int(100 / n))
    bar, caps = [], []
    for i, (caption, reached) in enumerate(stations):
        radius = ("4px 0 0 4px" if i == 0 else
                  "0 4px 4px 0" if i == n - 1 else "0")
        bar.append(f'<td width="{pct}%" height="7" style="background:'
                   f'{accent if reached else "#d9e2e0"};font-size:0;line-height:7px;'
                   f'border-radius:{radius}">&nbsp;</td>')
        if i:
            bar.insert(-1, '<td width="1" style="font-size:0">&nbsp;</td>')
        align = "left" if i == 0 else ("right" if i == n - 1 else "center")
        caps.append(f'<td align="{align}" style="padding-top:6px;font-size:11px;'
                    f'font-weight:600;color:{accent if reached else FAINT}">'
                    f'{esc(caption)}</td>')
    return (f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'role="presentation" style="border-collapse:collapse"><tr>{"".join(bar)}</tr></table>'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'role="presentation"><tr>{"".join(caps)}</tr></table>')


def envelope(*, accent, eyebrow, headline, figure=None, subline=None, lead=None,
             chip=None, rows=(), actions=(), footnote="", band=False, extra_html="",
             post_actions=""):
    """Assemble one email.

    band=True paints the whole header in the accent - reserved for a deadline or a
    welcome. Everything else gets the 4px rule.
    """
    rows_html = "".join(rows)
    # The first row's top border would double the header rule.
    if rows_html.startswith('<tr><td style="padding:7px 0;color:%s;width:44%%;border-top' % MUTED):
        rows_html = rows_html.replace(f"border-top:1px solid {HAIR};", "", 2)

    if band:
        head = (
            f'<tr><td style="background:{accent};padding:28px 32px 24px;border-radius:6px 6px 0 0">'
            f'<p style="margin:0 0 5px;font-family:{_MONO};font-size:11px;letter-spacing:.1em;'
            f'text-transform:uppercase;color:#ffffff;opacity:.78;font-weight:600">{esc(eyebrow)}</p>'
            f'<p style="margin:0;font-size:23px;line-height:1.25;color:#ffffff;font-weight:600;'
            f'font-family:{_AR};text-align:left" dir="auto">{esc(headline)}</p>'
            + (f'<p style="margin:6px 0 0;font-size:26px;line-height:1.2;color:#ffffff;'
               f'font-weight:700">{figure}</p>' if figure else "")
            + (f'<p style="margin:4px 0 0;font-size:13.5px;color:#ffffff;opacity:.85">'
               f'{esc(subline)}</p>' if subline else "")
            + '</td></tr>'
        )
    else:
        chip_html = ""
        if chip:
            chip_html = (
                f'<table cellpadding="0" cellspacing="0" border="0" role="presentation" '
                f'style="margin-bottom:10px"><tr><td style="background:{accent}1a;'
                f'border-radius:3px;padding:3px 9px;font-family:{_MONO};font-size:10.5px;'
                f'letter-spacing:.07em;text-transform:uppercase;color:{accent};'
                f'font-weight:600">{esc(chip)}</td></tr></table>')
        head = (
            f'<tr><td style="background:{accent};height:4px;line-height:4px;font-size:0;'
            f'border-radius:6px 6px 0 0">&nbsp;</td></tr>'
            f'<tr><td style="padding:26px 32px 0">{chip_html}'
            f'<p style="margin:0 0 6px;font-family:{_MONO};font-size:11px;letter-spacing:.09em;'
            f'text-transform:uppercase;color:{accent};font-weight:600">{esc(eyebrow)}</p>'
            f'<p style="margin:0 0 4px;font-size:20px;line-height:1.3;color:{INK};'
            f'font-weight:600;font-family:{_AR};text-align:left" dir="auto">{esc(headline)}</p>'
            + (f'<p style="margin:0;font-size:28px;line-height:1.2;color:{INK};'
               f'font-weight:700">{figure}</p>' if figure else "")
            + (f'<p style="margin:2px 0 0;font-size:13.5px;color:{MUTED}">{esc(subline)}</p>'
               if subline else "")
            + '</td></tr>'
        )

    lead_html = ""
    if lead:
        lead_html = (f'<tr><td style="padding:22px 32px 0;font-size:14.5px;color:{INK};'
                     f'line-height:1.6" dir="auto">{lead}</td></tr>')

    extra = f'<tr><td style="padding:20px 32px 0">{extra_html}</td></tr>' if extra_html else ""

    table = ""
    if rows_html:
        table = (f'<tr><td style="padding:18px 32px 0">'
                 f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                 f'role="presentation">{rows_html}</table></td></tr>')

    act = ""
    if actions:
        cells, primaries = [], [a for a in actions if a.get("href")]
        for i, b in enumerate(primaries):
            if i:
                cells.append('<td style="width:10px;font-size:0;line-height:1px">&nbsp;</td>')
            cells.append(_button_cell(b))
        act = (f'<table cellpadding="0" cellspacing="0" border="0" role="presentation">'
               f'<tr>{"".join(cells)}</tr></table>')

    foot = (f'<p style="margin:16px 0 0;font-size:12px;color:{FAINT};line-height:1.5">'
            f'{footnote + " " if footnote else ""}{esc(COMPANY)}</p>')

    if post_actions:
        act += f'<div style="margin-top:14px;font-size:13px">{post_actions}</div>'

    return f"""\
<table width="100%" cellpadding="0" cellspacing="0" border="0" role="presentation" \
style="background:#eef0f3;padding:18px 0">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" border="0" role="presentation" \
style="width:600px;max-width:100%;background:#ffffff;border-radius:6px;font-family:{_SANS}">
{head}{lead_html}{extra}{table}
<tr><td style="padding:22px 32px 28px">{act}{foot}</td></tr>
</table>
</td></tr></table>"""


# --------------------------------------------------------------- digest layout
# A digest is not a notice about one thing, it is a list. These two give it the
# same voice as the rest without pretending a table is a headline.


def stat_strip(items, accent=BRAND):
    """A row of figures across the top: [(value, caption), ...].

    Cells, not flexbox, and widths left to the table - Outlook ignores both
    `display:flex` and percentage widths on divs.
    """
    if not items:
        return ""
    cells = []
    for i, (value, caption) in enumerate(items):
        pad = "0 0 0 16px" if i else "0 16px 0 0"
        edge = ("border-left:1px solid %s;" % HAIR) if i else ""
        cells.append(
            f'<td style="{edge}padding:{pad};vertical-align:top">'
            f'<div style="font-size:22px;font-weight:700;color:{accent};'
            f'line-height:1.2">{value}</div>'
            f'<div style="font-size:11.5px;color:{MUTED};padding-top:2px">{esc(caption)}</div>'
            f'</td>')
    return (f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'role="presentation" style="margin-bottom:4px"><tr>{"".join(cells)}</tr></table>')


def section(title, accent=BRAND):
    return (f'<p style="margin:22px 0 8px;font-family:{_MONO};font-size:10.5px;'
            f'letter-spacing:.08em;text-transform:uppercase;color:{accent};'
            f'font-weight:600">{esc(title)}</p>')


def data_table(headers, rows, aligns=None, empty="Nothing here this week"):
    """A list of records. `rows` cells are TRUSTED html - escape before passing."""
    aligns = aligns or (["left"] * len(headers))
    if not rows:
        return (f'<p style="margin:0;font-size:13px;color:{MUTED}">{esc(empty)}</p>')
    head = "".join(
        f'<th align="{a}" style="padding:0 8px 6px 0;font-size:10.5px;'
        f'letter-spacing:.05em;text-transform:uppercase;color:{MUTED};'
        f'font-weight:600;border-bottom:1px solid {RULE_SOFT}">{esc(h)}</th>'
        for h, a in zip(headers, aligns))
    body = ""
    for r in rows:
        body += "<tr>" + "".join(
            f'<td align="{a}" style="padding:7px 8px 7px 0;font-size:13px;color:{INK};'
            f'border-bottom:1px solid {HAIR};vertical-align:top">{c}</td>'
            for c, a in zip(r, aligns)) + "</tr>"
    return (f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'role="presentation" style="border-collapse:collapse">'
            f'<tr>{head}</tr>{body}</table>')
