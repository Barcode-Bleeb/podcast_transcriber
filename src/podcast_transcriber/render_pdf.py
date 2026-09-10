"""Render a Summary into a styled PDF that echoes the user's template.

We use **fpdf2**: pure-Python, no system libraries, so it runs identically on
Windows and on the Raspberry Pi (unlike HTML-to-PDF tools that need heavy
native deps). The layout is fixed in code — the model only supplies content —
so every summary looks the same regardless of what the model returns.

Sections (any empty one is skipped):
  Theme blurb → Tags → Deep dives → Quick hits → Insights & quotes →
  To apply & explore → Resources.

Honest portability note: the built-in PDF fonts cover only Latin-1. Dutch
accented letters (é, ë, ï, …) are inside it, so ordinary Dutch text renders
fine; "smart" typography (curly quotes, em-dashes) is not, so we substitute
plain equivalents before drawing. A small typographic downgrade, not a content
loss; we can embed a full Unicode font later if desired.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from .summarize import Summary

# Colors (RGB)
_ACCENT = (13, 71, 82)      # dark teal for section bars and headings
_MUTED = (110, 110, 110)    # gray for meta / footer text
_INK = (30, 30, 30)         # near-black body text

# Section labels, localized to the summary's language (Dutch or English). These
# are navigational chrome set by our code, not by the model.
_LABELS = {
    "en": {
        "deep_dives": "DEEP DIVES",
        "quick_hits": "QUICK HITS",
        "insights": "KEY INSIGHTS & QUOTES",
        "actions": "TO APPLY & EXPLORE",
        "resources": "RESOURCES & REFERENCES",
        "apply": "Apply", "read": "Read", "tags": "Tags", "with": "with",
    },
    "nl": {
        "deep_dives": "VERDIEPING",
        "quick_hits": "KORT NIEUWS",
        "insights": "INZICHTEN & CITATEN",
        "actions": "OM TOE TE PASSEN & TE VERKENNEN",
        "resources": "BRONNEN & VERWIJZINGEN",
        "apply": "Toepassen", "read": "Lezen", "tags": "Tags", "met": "met",
    },
}

_SUBS = {
    "—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
    "…": "...", "•": "-", " ": " ", "​": "",
}


def _san(text: str) -> str:
    """Make text safe for the Latin-1 core fonts."""
    if not text:
        return ""
    for bad, good in _SUBS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


class _PodcastPDF(FPDF):
    footer_text: str = ""

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 10, _san(self.footer_text), align="C")


def _bar(pdf: _PodcastPDF, title: str) -> None:
    pdf.ln(3)
    pdf.set_fill_color(*_ACCENT)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 9, _san(title), new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.ln(2)


def _heading(pdf: _PodcastPDF, text: str) -> None:
    pdf.set_text_color(*_ACCENT)
    pdf.set_font("Helvetica", "B", 11)
    pdf.multi_cell(0, 6, _san(text), new_x="LMARGIN", new_y="NEXT")


def _body(pdf: _PodcastPDF, text: str, *, gap: float = 1.5) -> None:
    pdf.set_text_color(*_INK)
    pdf.set_font("Helvetica", "", 10.5)
    pdf.multi_cell(0, 5.4, _san(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(gap)


def render_summary_pdf(summary: Summary, *, show_name: str, episode_title: str,
                       date: str = "", episode_number: str = "",
                       out_path: Path, backend: str = "") -> Path:
    """Write the summary to a PDF at out_path and return it."""
    lang = "nl" if (summary.language or "").lower().startswith("nl") else "en"
    L = _LABELS[lang]

    pdf = _PodcastPDF(format="A4", unit="mm")
    ep = f"#{episode_number}" if episode_number else ""
    pdf.footer_text = " | ".join(
        p for p in ("Summary generated automatically", show_name, ep, date) if p
    )
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(20, 18, 20)
    pdf.add_page()

    # --- Title block ---
    pdf.set_text_color(*_ACCENT)
    pdf.set_font("Helvetica", "B", 18)
    pdf.multi_cell(0, 8, _san(show_name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*_INK)
    pdf.set_font("Helvetica", "B", 13)
    pdf.multi_cell(0, 6.5, _san(episode_title), new_x="LMARGIN", new_y="NEXT")
    if summary.guests:
        pdf.set_font("Helvetica", "I", 10.5)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(0, 6, _san(f"{L.get('with', 'with')} {summary.guests}"),
                       new_x="LMARGIN", new_y="NEXT")
    meta = " | ".join(p for p in (f"Episode {ep}" if ep else "", date) if p)
    if meta:
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(0, 5, _san(meta), new_x="LMARGIN", new_y="NEXT")

    # --- Theme blurb (a skimmable "in short") ---
    if summary.theme:
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 10.5)
        pdf.set_text_color(*_INK)
        pdf.multi_cell(0, 5.4, _san(summary.theme), new_x="LMARGIN", new_y="NEXT")

    # --- Tags ---
    if summary.tags:
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*_ACCENT)
        pdf.multi_cell(0, 5, _san(f"{L['tags']}: " + "  ·  ".join(summary.tags)),
                       new_x="LMARGIN", new_y="NEXT")

    # --- Deep dives ---
    if summary.deep_dives:
        _bar(pdf, L["deep_dives"])
        for item in summary.deep_dives:
            _heading(pdf, item.get("heading", ""))
            _body(pdf, item.get("body", ""))

    # --- Quick hits ---
    if summary.quick_hits:
        _bar(pdf, L["quick_hits"])
        for item in summary.quick_hits:
            topic = item.get("topic", "")
            take = item.get("takeaway", "")
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.set_text_color(*_INK)
            pdf.multi_cell(0, 5.4, _san(f"- {topic}"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10.5)
            pdf.multi_cell(0, 5.4, _san(f"   {take}"), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

    # --- Insights & quotes ---
    if summary.insights:
        _bar(pdf, L["insights"])
        for item in summary.insights:
            label = item.get("text", "")
            if item.get("is_quote"):
                label = f'"{label}"'
            _heading(pdf, label)
            _body(pdf, item.get("explanation", ""))

    # --- To apply & explore ---
    if summary.actions:
        _bar(pdf, L["actions"])
        for item in summary.actions:
            tag = L.get(item.get("kind", "apply"), L["apply"])
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.set_text_color(*_ACCENT)
            pdf.cell(pdf.get_string_width(_san(f"[{tag}] ")) + 1, 5.4,
                     _san(f"[{tag}]"), new_x="RIGHT", new_y="TOP")
            pdf.set_font("Helvetica", "", 10.5)
            pdf.set_text_color(*_INK)
            pdf.multi_cell(0, 5.4, _san(" " + item.get("text", "")),
                           new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

    # --- Resources ---
    if summary.resources:
        _bar(pdf, L["resources"])
        for i, item in enumerate(summary.resources, start=1):
            _heading(pdf, f"{i}. {item.get('title', '')}")
            author = item.get("author", "")
            if author:
                pdf.set_font("Helvetica", "I", 10)
                pdf.set_text_color(*_MUTED)
                pdf.multi_cell(0, 5, _san(f"{author}"),
                               new_x="LMARGIN", new_y="NEXT")
            _body(pdf, item.get("description", ""))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path
