"""Render a Summary into a styled PDF that echoes the user's template.

We use **fpdf2**: pure-Python, no system libraries, so it runs identically on
Windows and on the Raspberry Pi (unlike HTML-to-PDF tools that need heavy
native deps). The layout mirrors the example: a title block, three PART
sections with colored header bars, bold sub-headings, and a numbered
resources list.

One portability note, stated honestly: the built-in PDF fonts only cover the
Latin-1 character set. Dutch accented letters (é, ë, ï, …) are all inside it,
so ordinary Dutch text renders fine. But "smart" typography — curly quotes,
em-dashes, ellipses — is not, so we substitute plain equivalents before
drawing. It's a small typographic downgrade, not a content loss; we can embed
a full Unicode font later if you want the fancier punctuation back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fpdf import FPDF

from .summarize import Summary

# Colors (RGB)
_ACCENT = (13, 71, 82)      # dark teal for part bars and headings
_MUTED = (110, 110, 110)    # gray for meta / footer text
_INK = (30, 30, 30)         # near-black body text

# Map characters the core fonts can't draw to safe equivalents.
_SUBS = {
    "—": "-", "–": "-",           # em/en dash
    "‘": "'", "’": "'",           # curly single quotes
    "“": '"', "”": '"',           # curly double quotes
    "…": "...", "•": "-",          # ellipsis, bullet
    " ": " ", "​": "",             # nbsp, zero-width space
}


def _san(text: str) -> str:
    """Make text safe for the Latin-1 core fonts."""
    if not text:
        return ""
    for bad, good in _SUBS.items():
        text = text.replace(bad, good)
    # Anything still outside Latin-1 becomes '?', so we never crash on a stray glyph.
    return text.encode("latin-1", "replace").decode("latin-1")


class _PodcastPDF(FPDF):
    footer_text: str = ""

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 10, _san(self.footer_text), align="C")


def _part_bar(pdf: _PodcastPDF, title: str) -> None:
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


def _body(pdf: _PodcastPDF, text: str) -> None:
    pdf.set_text_color(*_INK)
    pdf.set_font("Helvetica", "", 10.5)
    pdf.multi_cell(0, 5.4, _san(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)


def render_summary_pdf(summary: Summary, *, show_name: str, episode_title: str,
                       date: str = "", episode_number: str = "",
                       out_path: Path, backend: str = "") -> Path:
    """Write the summary to a PDF at out_path and return it."""
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
    guests = (summary.header or {}).get("guests", "")
    if guests:
        pdf.set_font("Helvetica", "I", 10.5)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(0, 6, _san(f"with {guests}"), new_x="LMARGIN", new_y="NEXT")
    meta = " | ".join(p for p in (f"Episode {ep}" if ep else "", date) if p)
    if meta:
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(0, 5, _san(meta), new_x="LMARGIN", new_y="NEXT")

    # --- PART 1 ---
    _part_bar(pdf, "PART 1 - EPISODE SUMMARY")
    for item in summary.part1:
        _heading(pdf, item.get("heading", ""))
        _body(pdf, item.get("body", ""))

    # --- PART 2 ---
    _part_bar(pdf, "PART 2 - KEY INSIGHTS, QUOTES & TAKEAWAYS")
    for item in summary.part2:
        label = item.get("text", "")
        if item.get("is_quote"):
            label = f'"{label}"'
        _heading(pdf, label)
        _body(pdf, item.get("explanation", ""))

    # --- PART 3 ---
    if summary.part3:
        _part_bar(pdf, "PART 3 - BOOKS & RESOURCES MENTIONED")
        for i, item in enumerate(summary.part3, start=1):
            title = item.get("title", "")
            _heading(pdf, f"{i}. {title}")
            author = item.get("author", "")
            if author:
                pdf.set_font("Helvetica", "I", 10)
                pdf.set_text_color(*_MUTED)
                pdf.multi_cell(0, 5, _san(f"Author: {author}"),
                               new_x="LMARGIN", new_y="NEXT")
            _body(pdf, item.get("description", ""))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path
