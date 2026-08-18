from app.schemas import DiagramEdge, DiagramNode
from app.services.diagram_renderer import build_diagram_svg, render_diagram_png


class TestBuildDiagramSvg:
    def test_every_node_label_appears_in_the_svg(self) -> None:
        nodes = [DiagramNode(label="Input"), DiagramNode(label="Hidden Layer"), DiagramNode(label="Output")]
        svg, _, _ = build_diagram_svg(nodes, [])
        assert "Input" in svg
        assert "Hidden Layer" in svg
        assert "Output" in svg

    def test_edge_label_appears_in_the_svg(self) -> None:
        nodes = [DiagramNode(label="A"), DiagramNode(label="B")]
        edges = [DiagramEdge(from_index=0, to_index=1, label="produces")]
        svg, _, _ = build_diagram_svg(nodes, edges)
        assert "produces" in svg

    def test_edge_with_out_of_range_index_is_skipped_not_crashed(self) -> None:
        nodes = [DiagramNode(label="A"), DiagramNode(label="B")]
        edges = [DiagramEdge(from_index=0, to_index=5)]  # 5 doesn't exist
        svg, _, _ = build_diagram_svg(nodes, edges)  # must not raise
        assert "A" in svg and "B" in svg

    def test_self_referencing_edge_is_skipped(self) -> None:
        nodes = [DiagramNode(label="A")]
        edges = [DiagramEdge(from_index=0, to_index=0)]
        svg, _, _ = build_diagram_svg(nodes, edges)  # must not raise
        assert "A" in svg

    def test_label_containing_svg_special_characters_is_escaped(self) -> None:
        nodes = [DiagramNode(label="A < B & C > D")]
        svg, _, _ = build_diagram_svg(nodes, [])
        assert "<B" not in svg  # raw '<' would either break the XML or be misread as a tag
        assert "&lt;" in svg
        assert "&amp;" in svg
        assert "&gt;" in svg

    def test_returned_dimensions_match_the_svg_viewbox(self) -> None:
        nodes = [DiagramNode(label="A"), DiagramNode(label="B")]
        svg, width, height = build_diagram_svg(nodes, [])
        assert f'width="{width}"' in svg
        assert f'height="{height}"' in svg

    def test_more_than_four_nodes_wraps_to_a_second_row_and_grows_taller(self) -> None:
        two_nodes = [DiagramNode(label=f"N{i}") for i in range(2)]
        five_nodes = [DiagramNode(label=f"N{i}") for i in range(5)]
        _, _, short_height = build_diagram_svg(two_nodes, [])
        _, _, tall_height = build_diagram_svg(five_nodes, [])
        assert tall_height > short_height

    def test_valid_xml_structure(self) -> None:
        nodes = [DiagramNode(label="A"), DiagramNode(label="B")]
        edges = [DiagramEdge(from_index=0, to_index=1, label="x")]
        svg, _, _ = build_diagram_svg(nodes, edges)
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        # Balanced enough to actually render — the real correctness check is
        # test_render_diagram_png_produces_a_real_png below, which round-trips
        # this through the actual SVG parser rather than eyeballing tags.


class TestRenderDiagramPng:
    def test_produces_a_real_png(self) -> None:
        nodes = [DiagramNode(label="A"), DiagramNode(label="B")]
        edges = [DiagramEdge(from_index=0, to_index=1)]
        svg, _, _ = build_diagram_svg(nodes, edges)

        png_bytes = render_diagram_png(svg)

        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"  # PNG file signature
        assert len(png_bytes) > 100
