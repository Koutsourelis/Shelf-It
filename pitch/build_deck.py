"""Builds pitch/pitch.pptx from the CONTENT block below.

    pip install python-pptx
    python pitch/build_deck.py

Edit CONTENT, run again, done. Or open pitch.pptx and edit by hand (then stop running this script,
it overwrites the file). Text in [brackets] is a placeholder: none should survive to the final deck.
Speaker notes on every slide say what to say and how long to stay.
"""
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

CONTENT = {
    "name": "[Project name]",
    "one_liner": "[Who it is for] get [the tedious job] done by an agent that finishes it, not one that only advises.",
    "team": "[Name · Name · Name · Name]",
    "event": "Gen AI Summit Hackathon · Athens · 14–15 November 2026",
    "track": "[Track]",

    "problem_stat": "[6 h]",
    "problem_stat_label": "[per week, per person, lost to this job]",
    "problem_title": "[The job nobody wants, in the user's words]",
    "pains": [
        ("[Pain 1 in five words]", "[One line: what goes wrong today and what it costs.]"),
        ("[Pain 2 in five words]", "[One line: why existing tools do not solve it.]"),
        ("[Pain 3 in five words]", "[One line: what happens when it is done late or wrong.]"),
    ],

    "solution_title": "[Name] does the whole job, start to finish",
    "before": ["[Step the person does by hand today]", "[Second manual step]", "[Third manual step]",
               "[Result: late, partial, error-prone]"],
    "after": ["[Agent notices the trigger on its own]", "[Agent investigates and prepares the action]",
              "[Person approves with one tap]", "[Result: done, with proof of every number]"],

    "demo_title": "Live demo: three moments to watch",
    "demo_moments": [
        ("It starts on its own", "[What changes in the data and how the agent notices, with no one asking.]"),
        ("It asks before it acts", "[The action it prepares, and the approval that arrives on the phone.]"),
        ("It delivers", "[The finished piece of work: file, email, order. Name it.]"),
    ],

    "how_title": "How it works",
    "flow": ["Trigger", "Plan", "Tools", "Checks in code", "Approval", "Deliverable"],
    "how_points": [
        ("Code does the math", "Every number on screen comes from SQL or a calculator, never from the model's head."),
        ("Audit trail", "Each figure links back to the document or formula it came from."),
        ("Human in the loop", "Nothing leaves the building without one explicit yes."),
    ],

    "built_title": "Built in 29 hours",
    "built": ["[Feature built during the hackathon]", "[Feature built during the hackathon]",
              "[Feature built during the hackathon]", "[Feature built during the hackathon]"],
    "boilerplate": ["Generic agent loop and console", "General tools: files, SQL, web, browser, email, PDF",
                    "Synthetic sample data"],
    "stack": ["Gemini 3.8 Flash", "treg", "fal", "Open Food Facts", "Python · FastAPI", "DuckDB"],
    "stack_line": "Market evidence via treg: live web search, news and Google search trends.",

    "next_title": "What comes next",
    "next": [
        ("Next week", "[First real user or pilot you can name.]"),
        ("Next month", "[The integration that makes it usable daily.]"),
        ("Business", "[Who pays, roughly how much, and why it is worth it to them.]"),
    ],
    "closing": "[One closing sentence the judges should remember.]",
    "contact": "[github.com/… · contact]",
}

# Palette shared with the console, so the deck and the live demo look like one product.
BG, PANEL, PANEL2, LINE = "0F1318", "171C23", "1E252E", "2B343F"
TEXT, MUTED, ACCENT, OK, WARN = "E6EAEF", "93A1B0", "7EA2FF", "5FD08F", "F0B860"
HEAD, BODY = "Arial", "Calibri"
W, H, M = 13.333, 7.5, 0.7


def rgb(h):
    return RGBColor.from_string(h)


class Deck:
    def __init__(self):
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(W), Inches(H)
        self.n = 0

    def slide(self, notes):
        s = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = rgb(BG)
        s.notes_slide.notes_text_frame.text = notes
        self.n += 1
        self.s = s
        if self.n > 1:
            self.text(CONTENT["name"], M, H - 0.55, 6, 0.3, size=11, color=MUTED)
            self.text(str(self.n), W - M - 1, H - 0.55, 1, 0.3, size=11, color=MUTED, align=PP_ALIGN.RIGHT)
        return s

    def text(self, t, x, y, w, h, size=16, color=TEXT, bold=False, font=BODY, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP, spacing=None):
        tb = self.s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = anchor
        lines = t if isinstance(t, list) else [t]
        for i, line in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = align
            if spacing:
                p.space_after = Pt(spacing)
            r = p.add_run()
            r.text = line
            f = r.font
            f.size, f.bold, f.name = Pt(size), bold, font
            f.color.rgb = rgb(color)
        return tb

    def title(self, t):
        self.text(t, M, 0.55, W - 2 * M, 1.0, size=36, bold=True, font=HEAD, anchor=MSO_ANCHOR.MIDDLE)

    def box(self, x, y, w, h, fill=PANEL, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06):
        sh = self.s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
        if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
            sh.adjustments[0] = radius
        sh.fill.solid()
        sh.fill.fore_color.rgb = rgb(fill)
        if line:
            sh.line.color.rgb = rgb(line)
            sh.line.width = Pt(1)
        else:
            sh.line.fill.background()
        sh.shadow.inherit = False
        return sh

    def badge(self, label, x, y, d=0.6, fill=ACCENT, color=BG, size=18):
        """The deck's motif: a filled circle with a number or mark."""
        sh = self.box(x, y, d, d, fill=fill, shape=MSO_SHAPE.OVAL)
        tf = sh.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = label
        r.font.size, r.font.bold, r.font.name = Pt(size), True, HEAD
        r.font.color.rgb = rgb(color)


def build(out: Path):
    C, d = CONTENT, Deck()

    # 1 — Title
    d.slide("10 seconds. Say the name and the one-liner exactly as written, then go straight to the problem. "
            "Do not introduce the team here; that is the last slide.")
    d.badge("▸", M, 1.2, d=0.9, size=30)
    d.text(C["name"], M, 2.4, W - 2 * M, 1.3, size=60, bold=True, font=HEAD, anchor=MSO_ANCHOR.MIDDLE)
    d.text(C["one_liner"], M, 3.85, 9.6, 1.3, size=24, color=MUTED)
    d.text(C["team"], M, H - 1.55, 8, 0.4, size=16, bold=True)
    d.text(f"{C['event']} · {C['track']}", M, H - 1.1, 10, 0.4, size=14, color=MUTED)

    # 2 — Problem
    d.slide("25 seconds. Start with the number. Tell it as one person's Tuesday morning, not as a market overview. "
            "Say where the number comes from (interview, own experience, public source).")
    d.title(C["problem_title"])
    d.box(M, 2.0, 4.4, 4.3, fill=PANEL)
    d.text(C["problem_stat"], M + 0.4, 2.5, 3.6, 1.6, size=80, bold=True, font=HEAD, color=ACCENT, anchor=MSO_ANCHOR.MIDDLE)
    d.text(C["problem_stat_label"], M + 0.4, 4.3, 3.6, 1.4, size=18, color=MUTED)
    for i, (head, line) in enumerate(C["pains"]):
        y = 2.0 + i * 1.5
        d.badge(str(i + 1), 5.6, y + 0.1, fill=PANEL2, color=ACCENT)
        d.text(head, 6.5, y, 6.1, 0.45, size=20, bold=True)
        d.text(line, 6.5, y + 0.5, 6.1, 0.8, size=16, color=MUTED)

    # 3 — Solution: before / after
    d.slide("20 seconds. Read only the last line of each column aloud. The contrast is the message: "
            "today a person does every step, with us the person only approves.")
    d.title(C["solution_title"])
    for col, (label, items, color, fill) in enumerate([("Today", C["before"], MUTED, PANEL),
                                                       ("With the agent", C["after"], OK, PANEL2)]):
        x = M + col * 6.1
        d.box(x, 2.0, 5.8, 4.5, fill=fill)
        d.text(label.upper(), x + 0.4, 2.3, 5, 0.4, size=13, bold=True, color=color)
        for i, item in enumerate(items):
            y = 2.95 + i * 0.85
            last = i == len(items) - 1
            mark = ("✓" if col else "→") if last else str(i + 1)
            d.badge(mark, x + 0.4, y, d=0.45, size=13, fill=color if last else LINE, color=BG if last else TEXT)
            d.text(item, x + 1.05, y, 4.4, 0.45, size=16, bold=last, anchor=MSO_ANCHOR.MIDDLE,
                   color=TEXT if (col or last) else MUTED)

    # 4 — Demo
    d.slide("Leave this slide after 10 seconds and switch to the console in presentation mode (key P). "
            "Name the three moments first so the judges know what to look for. "
            "If anything fails: play the recorded run or the video, and keep talking. See DEMO_SCRIPT.md.")
    d.title(C["demo_title"])
    for i, (head, line) in enumerate(C["demo_moments"]):
        x = M + i * 4.05
        d.box(x, 2.0, 3.8, 4.3, fill=PANEL)
        d.badge(str(i + 1), x + 0.4, 2.4, d=0.8, size=24, fill=[ACCENT, WARN, OK][i])
        d.text(head, x + 0.4, 3.5, 3.0, 0.9, size=22, bold=True, font=HEAD)
        d.text(line, x + 0.4, 4.45, 3.0, 1.6, size=16, color=MUTED)

    # 5 — How it works
    d.slide("20 seconds. Point at 'Checks in code' and say the one sentence that builds trust: "
            "the model reads and decides what to do, but every number is computed by code and can be traced. "
            "Skip the rest unless a judge asks.")
    d.title(C["how_title"])
    n, bw = len(C["flow"]), 1.75
    gap = (W - 2 * M - n * bw) / (n - 1)
    for i, step in enumerate(C["flow"]):
        x = M + i * (bw + gap)
        key = step == "Checks in code"
        d.box(x, 2.0, bw, 1.0, fill=ACCENT if key else PANEL, line=None if key else LINE)
        d.text(step, x + 0.1, 2.0, bw - 0.2, 1.0, size=15, bold=True, color=BG if key else TEXT,
               align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        if i < n - 1:
            d.text("›", x + bw, 2.0, gap, 1.0, size=24, color=MUTED, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    for i, (head, line) in enumerate(C["how_points"]):
        x = M + i * 4.05
        d.box(x, 3.6, 3.8, 2.7, fill=PANEL)
        d.badge("✓", x + 0.4, 3.95, d=0.5, size=14, fill=OK)
        d.text(head, x + 1.1, 3.95, 2.5, 0.5, size=18, bold=True, anchor=MSO_ANCHOR.MIDDLE)
        d.text(line, x + 0.4, 4.75, 3.0, 1.3, size=16, color=MUTED)

    # 6 — Built during the hackathon
    d.slide("15 seconds. Be exact about what was built this weekend and what was boilerplate; the judges score only "
            "the weekend's work and they respect teams that say so plainly. The git history shows the same split. "
            "Name the sponsor tools out loud: market evidence via treg (live web search, news and Google search "
            "trends), shelf talkers via fal.")
    d.title(C["built_title"])
    d.box(M, 2.0, 7.2, 3.4, fill=PANEL2)
    d.text("BUILT THIS WEEKEND", M + 0.4, 2.25, 6, 0.4, size=13, bold=True, color=OK)
    for i, item in enumerate(C["built"]):
        d.badge("✓", M + 0.4, 2.85 + i * 0.6, d=0.36, size=11, fill=OK)
        d.text(item, M + 0.95, 2.85 + i * 0.6, 6.0, 0.36, size=16, anchor=MSO_ANCHOR.MIDDLE)
    d.box(M + 7.5, 2.0, W - 2 * M - 7.5, 3.4, fill=PANEL)
    d.text("PREPARED BEFORE (DECLARED)", M + 7.9, 2.25, 4, 0.4, size=13, bold=True, color=MUTED)
    d.text(C["boilerplate"], M + 7.9, 2.85, 3.7, 2.4, size=15, color=MUTED, spacing=10)
    cw = (W - 2 * M - 5 * 0.2) / 6
    for i, chip in enumerate(C["stack"]):
        x = M + i * (cw + 0.2)
        d.box(x, 5.75, cw, 0.6, fill=BG, line=LINE, radius=0.5)
        d.text(chip, x, 5.75, cw, 0.6, size=14, color=TEXT, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    d.text(C["stack_line"], M, 6.5, W - 2 * M, 0.4, size=14, color=MUTED, align=PP_ALIGN.CENTER)

    # 7 — Next + close
    d.slide("15 seconds. One concrete next step, then the closing sentence, then stop talking. "
            "Introduce the team by first name and role in one breath. Leave this slide up during questions.")
    d.title(C["next_title"])
    for i, (head, line) in enumerate(C["next"]):
        x = M + i * 4.05
        d.box(x, 2.0, 3.8, 2.3, fill=PANEL)
        d.text(head.upper(), x + 0.4, 2.25, 3.0, 0.4, size=13, bold=True, color=ACCENT)
        d.text(line, x + 0.4, 2.8, 3.0, 1.3, size=16)
    d.text(C["closing"], M, 4.75, W - 2 * M, 0.9, size=26, bold=True, font=HEAD, anchor=MSO_ANCHOR.MIDDLE)
    d.text(C["team"], M, 5.85, 8, 0.4, size=16, bold=True)
    d.text(C["contact"], M, 6.25, 8, 0.4, size=14, color=MUTED)

    d.prs.save(out)
    print("Wrote", out)


if __name__ == "__main__":
    build(Path(__file__).resolve().parent / "pitch.pptx")
