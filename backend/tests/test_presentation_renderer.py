from pathlib import Path

from pptx import Presentation as PptxPresentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.schemas import DiagramEdge, DiagramNode, PresentationGenerationResult, SlideColumn, SlideLayout, SlideResult
from app.services.presentation_renderer import render_presentation


def _all_text(slide) -> str:
    return "\n".join(shape.text_frame.text for shape in slide.shapes if shape.has_text_frame)


class TestRenderPresentation:
    def test_renders_one_slide_per_plan_entry(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(
            slides=[
                SlideResult(layout=SlideLayout.TITLE, title="Deck Title"),
                SlideResult(layout=SlideLayout.BULLETS, title="Topic", lines=["A", "B"]),
                SlideResult(layout=SlideLayout.QUOTE, title="fallback", quote="A quote."),
            ]
        )
        out = tmp_path / "deck.pptx"

        render_presentation(result, out, "Notebook")

        deck = PptxPresentation(str(out))
        assert len(deck.slides) == 3

    def test_output_file_exists_and_is_a_valid_pptx(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(slides=[SlideResult(layout=SlideLayout.TITLE, title="X")])
        out = tmp_path / "nested" / "deck.pptx"

        render_presentation(result, out, "Notebook")

        assert out.exists()
        # Round-trips through python-pptx without raising — proves the XML
        # produced is well-formed and PowerPoint-compatible, not just "a
        # file got written somewhere."
        reopened = PptxPresentation(str(out))
        assert len(reopened.slides) == 1

    def test_title_slide_shows_title_and_subtitle(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(
            slides=[SlideResult(layout=SlideLayout.TITLE, title="Neural Networks 101", subtitle="An intro")]
        )
        out = tmp_path / "deck.pptx"

        render_presentation(result, out, "Notebook")

        text = _all_text(PptxPresentation(str(out)).slides[0])
        assert "Neural Networks 101" in text
        assert "An intro" in text

    def test_bullets_slide_shows_heading_and_every_line(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(
            slides=[
                SlideResult(
                    layout=SlideLayout.BULLETS, title="Key Concepts", lines=["First point", "Second point"]
                )
            ]
        )
        out = tmp_path / "deck.pptx"

        render_presentation(result, out, "Notebook")

        text = _all_text(PptxPresentation(str(out)).slides[0])
        assert "Key Concepts" in text
        assert "First point" in text
        assert "Second point" in text

    def test_two_column_slide_shows_both_columns(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(
            slides=[
                SlideResult(
                    layout=SlideLayout.TWO_COLUMN,
                    title="Architectures",
                    columns=[
                        SlideColumn(heading="CNNs", lines=["Good for images"]),
                        SlideColumn(heading="RNNs", lines=["Good for sequences"]),
                    ],
                )
            ]
        )
        out = tmp_path / "deck.pptx"

        render_presentation(result, out, "Notebook")

        text = _all_text(PptxPresentation(str(out)).slides[0])
        assert "CNNs" in text
        assert "Good for images" in text
        assert "RNNs" in text
        assert "Good for sequences" in text

    def test_comparison_slide_shows_both_columns(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(
            slides=[
                SlideResult(
                    layout=SlideLayout.COMPARISON,
                    title="Supervised vs Unsupervised",
                    columns=[
                        SlideColumn(heading="Supervised", lines=["Labeled data"]),
                        SlideColumn(heading="Unsupervised", lines=["No labels"]),
                    ],
                )
            ]
        )
        out = tmp_path / "deck.pptx"

        render_presentation(result, out, "Notebook")

        text = _all_text(PptxPresentation(str(out)).slides[0])
        assert "Supervised" in text
        assert "Unsupervised" in text

    def test_quote_slide_shows_quote_and_attribution(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(
            slides=[
                SlideResult(
                    layout=SlideLayout.QUOTE,
                    title="fallback title (unused for this layout)",
                    quote="All models are wrong, but some are useful.",
                    attribution="George Box",
                )
            ]
        )
        out = tmp_path / "deck.pptx"

        render_presentation(result, out, "Notebook")

        text = _all_text(PptxPresentation(str(out)).slides[0])
        assert "All models are wrong, but some are useful." in text
        assert "George Box" in text

    def test_quote_slide_with_no_title_still_renders_the_quote(self, tmp_path: Path) -> None:
        # Regression case: title has no schema-level minimum length, so a
        # quote slide can validly arrive with title omitted/empty — the
        # layout never displays title anyway, so this must render cleanly.
        result = PresentationGenerationResult(
            slides=[SlideResult(layout=SlideLayout.QUOTE, quote="A quote with no title set at all.")]
        )
        out = tmp_path / "deck.pptx"

        render_presentation(result, out, "Notebook")

        text = _all_text(PptxPresentation(str(out)).slides[0])
        assert "A quote with no title set at all." in text

    def test_quote_slide_falls_back_to_title_when_quote_is_missing(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(
            slides=[SlideResult(layout=SlideLayout.QUOTE, title="Used as the quote text")]
        )
        out = tmp_path / "deck.pptx"

        render_presentation(result, out, "Notebook")

        text = _all_text(PptxPresentation(str(out)).slides[0])
        assert "Used as the quote text" in text

    def test_diagram_slide_embeds_a_picture_and_shows_heading_and_caption(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(
            slides=[
                SlideResult(
                    layout=SlideLayout.DIAGRAM,
                    title="The Pipeline",
                    nodes=[DiagramNode(label="Input"), DiagramNode(label="Output")],
                    edges=[DiagramEdge(from_index=0, to_index=1, label="transform")],
                    caption="Data flows from input to output.",
                )
            ]
        )
        out = tmp_path / "deck.pptx"

        render_presentation(result, out, "Notebook")

        slide = PptxPresentation(str(out)).slides[0]
        pictures = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE]
        assert len(pictures) == 1
        text = _all_text(slide)
        assert "The Pipeline" in text
        assert "Data flows from input to output." in text

    def test_diagram_picture_stays_within_slide_bounds(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(
            slides=[
                SlideResult(
                    layout=SlideLayout.DIAGRAM,
                    title="Big Diagram",
                    nodes=[DiagramNode(label=f"Step {i}") for i in range(6)],
                    edges=[DiagramEdge(from_index=i, to_index=i + 1) for i in range(5)],
                    caption="Six steps, wrapping across two rows.",
                )
            ]
        )
        out = tmp_path / "deck.pptx"

        render_presentation(result, out, "Notebook")

        slide = PptxPresentation(str(out)).slides[0]
        deck = PptxPresentation(str(out))
        picture = next(s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.PICTURE)
        assert picture.left >= 0
        assert picture.top >= 0
        assert picture.left + picture.width <= deck.slide_width
        assert picture.top + picture.height <= deck.slide_height

    def test_diagram_slide_without_caption_has_no_caption_text(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(
            slides=[
                SlideResult(
                    layout=SlideLayout.DIAGRAM,
                    title="No Caption Here",
                    nodes=[DiagramNode(label="A"), DiagramNode(label="B")],
                )
            ]
        )
        out = tmp_path / "deck.pptx"

        render_presentation(result, out, "Notebook")

        slide = PptxPresentation(str(out)).slides[0]
        # heading + accent rule + picture + footer = 4 shapes, no 5th (caption) shape
        assert len(slide.shapes) == 4

    def test_watermark_appears_on_non_title_slides_but_not_the_title_slide(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(
            slides=[
                SlideResult(layout=SlideLayout.TITLE, title="Cover"),
                SlideResult(layout=SlideLayout.BULLETS, title="Body", lines=["A"]),
            ]
        )
        out = tmp_path / "deck.pptx"

        render_presentation(result, out, "Notebook")

        deck = PptxPresentation(str(out))
        assert "Generated with StudyMind" not in _all_text(deck.slides[0])
        assert "Generated with StudyMind" in _all_text(deck.slides[1])

    def test_missing_output_directory_is_created(self, tmp_path: Path) -> None:
        result = PresentationGenerationResult(slides=[SlideResult(layout=SlideLayout.TITLE, title="X")])
        out = tmp_path / "a" / "b" / "c" / "deck.pptx"

        render_presentation(result, out, "Notebook")

        assert out.exists()
