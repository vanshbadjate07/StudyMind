import io
from pathlib import Path

from pptx import Presentation as PptxPresentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from pptx.slide import Slide
from pptx.util import Emu, Inches, Pt

from app.schemas import PresentationGenerationResult, SlideResult
from app.services.diagram_renderer import build_diagram_svg, render_diagram_png

# 16:9 widescreen, matching every modern presentation tool's default.
SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)

MARGIN = Inches(0.6)
CONTENT_WIDTH = SLIDE_WIDTH - 2 * MARGIN

HEADING_FONT = "Georgia"
BODY_FONT = "Calibri"

# Warm, professional palette — deliberately not the purple/indigo-gradient
# "AI generated" default. Two accents (teal / amber) give comparison slides
# a real visual contrast instead of two identical-looking columns.
BACKGROUND = RGBColor(0xF7, 0xF4, 0xEE)
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x6B, 0x6B, 0x63)
ACCENT_A = RGBColor(0x1B, 0x6E, 0x63)
ACCENT_B = RGBColor(0xC9, 0x7B, 0x2E)

WATERMARK_TEXT = "Generated with StudyMind"


def render_presentation(result: PresentationGenerationResult, output_path: Path, notebook_title: str) -> None:
    """Renders a validated slide plan to a real .pptx file. Pure function of
    its inputs — no LLM or DB involvement — so it's testable by feeding it a
    PresentationGenerationResult directly and inspecting the output file."""
    deck = PptxPresentation()
    deck.slide_width = SLIDE_WIDTH
    deck.slide_height = SLIDE_HEIGHT
    blank_layout = deck.slide_layouts[6]  # "Blank" — every element is placed explicitly below

    for index, slide_plan in enumerate(result.slides):
        slide = deck.slides.add_slide(blank_layout)
        _fill_background(slide)
        _render_slide_body(slide, slide_plan)
        if slide_plan.layout.value != "title":
            _add_footer(slide, page_number=index + 1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    deck.save(str(output_path))


def _render_slide_body(slide: Slide, plan: SlideResult) -> None:
    if plan.layout.value == "title":
        _render_title_slide(slide, plan)
    elif plan.layout.value == "bullets":
        _render_bullets_slide(slide, plan)
    elif plan.layout.value in ("two_column", "comparison"):
        _render_two_column_slide(slide, plan, contrast=plan.layout.value == "comparison")
    elif plan.layout.value == "quote":
        _render_quote_slide(slide, plan)
    elif plan.layout.value == "diagram":
        _render_diagram_slide(slide, plan)


def _fill_background(slide: Slide) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = BACKGROUND


def _add_footer(slide: Slide, page_number: int) -> None:
    box = slide.shapes.add_textbox(MARGIN, SLIDE_HEIGHT - Inches(0.45), CONTENT_WIDTH, Inches(0.3))
    tf = box.text_frame
    tf.margin_top = 0
    tf.margin_bottom = 0
    para = tf.paragraphs[0]
    run = para.add_run()
    run.text = f"{WATERMARK_TEXT}   ·   {page_number}"
    run.font.name = BODY_FONT
    run.font.size = Pt(9)
    run.font.color.rgb = MUTED
    para.alignment = PP_ALIGN.RIGHT


def _render_title_slide(slide: Slide, plan: SlideResult) -> None:
    # Accent bar down the left edge — a consistent brand mark, cheap to
    # render, present on the opening slide the way a cover page has one.
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(0), Emu(0), Inches(0.2), SLIDE_HEIGHT)
    bar.fill.solid()
    bar.fill.fore_color.rgb = ACCENT_A
    bar.line.fill.background()

    title_box = slide.shapes.add_textbox(Inches(1.0), Inches(2.8), SLIDE_WIDTH - Inches(2.0), Inches(1.6))
    tf = title_box.text_frame
    tf.word_wrap = True
    para = tf.paragraphs[0]
    run = para.add_run()
    run.text = plan.title
    run.font.name = HEADING_FONT
    run.font.size = Pt(40)
    run.font.bold = True
    run.font.color.rgb = INK

    if plan.subtitle:
        sub_box = slide.shapes.add_textbox(Inches(1.0), Inches(4.3), SLIDE_WIDTH - Inches(2.0), Inches(1.0))
        sub_tf = sub_box.text_frame
        sub_tf.word_wrap = True
        sub_para = sub_tf.paragraphs[0]
        sub_run = sub_para.add_run()
        sub_run.text = plan.subtitle
        sub_run.font.name = BODY_FONT
        sub_run.font.size = Pt(18)
        sub_run.font.color.rgb = MUTED


def _render_heading(slide: Slide, text: str) -> None:
    box = slide.shapes.add_textbox(MARGIN, Inches(0.5), CONTENT_WIDTH, Inches(0.9))
    tf = box.text_frame
    tf.word_wrap = True
    para = tf.paragraphs[0]
    run = para.add_run()
    run.text = text
    run.font.name = HEADING_FONT
    run.font.size = Pt(28)
    run.font.bold = True
    run.font.color.rgb = INK

    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, MARGIN, Inches(1.35), Inches(1.1), Pt(4))
    rule.fill.solid()
    rule.fill.fore_color.rgb = ACCENT_A
    rule.line.fill.background()


def _set_bullet_color(paragraph, color: RGBColor) -> None:
    """python-pptx has no high-level bullet API — customizing the bullet
    character's color requires touching the paragraph's raw XML properties
    directly. Falls back to the default bullet (no custom color) if the
    paragraph has no pPr element yet, which shouldn't happen in practice
    since add_run() creates one, but this must never crash a whole
    presentation over a cosmetic detail."""
    pPr = paragraph._pPr
    if pPr is None:
        return
    buClr = pPr.makeelement(qn("a:buClr"), {})
    srgbClr = buClr.makeelement(qn("a:srgbClr"), {"val": f"{color}"})
    buClr.append(srgbClr)
    pPr.append(buClr)


def _add_bullet_list(slide: Slide, left, top, width, height, lines: list[str], accent: RGBColor) -> None:
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.space_after = Pt(10)
        run = para.add_run()
        run.text = line
        run.font.name = BODY_FONT
        run.font.size = Pt(18)
        run.font.color.rgb = INK
        _set_bullet_color(para, accent)


def _render_bullets_slide(slide: Slide, plan: SlideResult) -> None:
    _render_heading(slide, plan.title)
    _add_bullet_list(
        slide, MARGIN, Inches(1.7), CONTENT_WIDTH, SLIDE_HEIGHT - Inches(2.3), plan.lines, ACCENT_A
    )


def _render_two_column_slide(slide: Slide, plan: SlideResult, *, contrast: bool) -> None:
    _render_heading(slide, plan.title)

    columns = plan.columns[:2]
    gap = Inches(0.5)
    column_width = (CONTENT_WIDTH - gap) / 2
    top = Inches(1.9)

    accents = [ACCENT_A, ACCENT_B] if contrast else [ACCENT_A, ACCENT_A]

    for i, column in enumerate(columns):
        left = MARGIN + i * (column_width + gap)
        heading_box = slide.shapes.add_textbox(left, top, column_width, Inches(0.5))
        heading_tf = heading_box.text_frame
        heading_tf.word_wrap = True
        heading_para = heading_tf.paragraphs[0]
        heading_run = heading_para.add_run()
        heading_run.text = column.heading
        heading_run.font.name = HEADING_FONT
        heading_run.font.size = Pt(18)
        heading_run.font.bold = True
        heading_run.font.color.rgb = accents[i]

        _add_bullet_list(
            slide,
            left,
            top + Inches(0.6),
            column_width,
            SLIDE_HEIGHT - top - Inches(1.1),
            column.lines,
            accents[i],
        )

    if contrast and len(columns) == 2:
        divider = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, MARGIN + column_width + gap / 2, top, Pt(2), SLIDE_HEIGHT - top - Inches(0.9)
        )
        divider.fill.solid()
        divider.fill.fore_color.rgb = MUTED
        divider.line.fill.background()


def _render_quote_slide(slide: Slide, plan: SlideResult) -> None:
    mark = slide.shapes.add_textbox(Inches(1.0), Inches(1.5), Inches(1.5), Inches(1.2))
    mark_tf = mark.text_frame
    mark_para = mark_tf.paragraphs[0]
    mark_run = mark_para.add_run()
    mark_run.text = "“"
    mark_run.font.name = HEADING_FONT
    mark_run.font.size = Pt(72)
    mark_run.font.bold = True
    mark_run.font.color.rgb = ACCENT_A

    quote_box = slide.shapes.add_textbox(Inches(1.3), Inches(2.6), SLIDE_WIDTH - Inches(2.6), Inches(2.2))
    quote_tf = quote_box.text_frame
    quote_tf.word_wrap = True
    quote_tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    quote_para = quote_tf.paragraphs[0]
    quote_para.alignment = PP_ALIGN.CENTER
    quote_run = quote_para.add_run()
    quote_run.text = plan.quote or plan.title
    quote_run.font.name = HEADING_FONT
    quote_run.font.size = Pt(30)
    quote_run.font.italic = True
    quote_run.font.color.rgb = INK

    if plan.attribution:
        attr_box = slide.shapes.add_textbox(Inches(1.3), Inches(5.0), SLIDE_WIDTH - Inches(2.6), Inches(0.6))
        attr_tf = attr_box.text_frame
        attr_para = attr_tf.paragraphs[0]
        attr_para.alignment = PP_ALIGN.CENTER
        attr_run = attr_para.add_run()
        attr_run.text = f"— {plan.attribution}"
        attr_run.font.name = BODY_FONT
        attr_run.font.size = Pt(16)
        attr_run.font.color.rgb = MUTED


def _render_diagram_slide(slide: Slide, plan: SlideResult) -> None:
    _render_heading(slide, plan.title)

    svg, svg_width, svg_height = build_diagram_svg(plan.nodes, plan.edges)
    png_bytes = render_diagram_png(svg)

    top = Inches(1.8)
    caption_reserve = Inches(0.6) if plan.caption else Inches(0)
    available_width = CONTENT_WIDTH
    available_height = SLIDE_HEIGHT - top - Inches(0.7) - caption_reserve

    # Fit the diagram's natural aspect ratio within the available box
    # ("object-fit: contain") rather than stretching it — a stretched
    # diagram would distort the node boxes into non-square rectangles.
    scale = min(available_width / svg_width, available_height / svg_height)
    picture_width = Emu(int(svg_width * scale))
    picture_height = Emu(int(svg_height * scale))
    left = MARGIN + (available_width - picture_width) // 2
    picture_top = top + (available_height - picture_height) // 2

    slide.shapes.add_picture(
        io.BytesIO(png_bytes), left, picture_top, width=picture_width, height=picture_height
    )

    if plan.caption:
        caption_box = slide.shapes.add_textbox(
            MARGIN, SLIDE_HEIGHT - Inches(1.15), CONTENT_WIDTH, Inches(0.5)
        )
        caption_tf = caption_box.text_frame
        caption_tf.word_wrap = True
        caption_para = caption_tf.paragraphs[0]
        caption_para.alignment = PP_ALIGN.CENTER
        caption_run = caption_para.add_run()
        caption_run.text = plan.caption
        caption_run.font.name = BODY_FONT
        caption_run.font.size = Pt(15)
        caption_run.font.italic = True
        caption_run.font.color.rgb = MUTED
