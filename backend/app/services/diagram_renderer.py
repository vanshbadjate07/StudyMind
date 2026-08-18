import resvg_py

from app.schemas import DiagramEdge, DiagramNode

# Matches presentation_renderer's palette exactly, as hex strings (SVG wants
# "#RRGGBB", not python-pptx's RGBColor) — kept in sync manually since these
# are two different libraries' color types, not worth a shared abstraction
# for four constants.
_BACKGROUND = "#F7F4EE"
_INK = "#1A1A1A"
_ACCENT_A = "#1B6E63"
_MUTED = "#6B6B63"

_CANVAS_WIDTH = 1400
_NODE_WIDTH = 220
_NODE_HEIGHT = 110
_ROW_GAP = 80
_CANVAS_MARGIN = 60
_MAX_PER_ROW = 4


def _canvas_height(rows: int) -> int:
    return rows * _NODE_HEIGHT + (rows - 1) * _ROW_GAP + 2 * _CANVAS_MARGIN


def _node_positions(count: int) -> list[tuple[int, int]]:
    """Lays nodes out left-to-right, wrapping to a new row after
    _MAX_PER_ROW — deterministic and simple by design: this covers the
    common case a study-material diagram actually needs (a linear process,
    pipeline, or short sequence), not an arbitrary graph layout. Positions
    are the top-left corner of each node's box. Canvas height (via
    _canvas_height) scales with row count, so a common 1-row diagram (2-4
    nodes) doesn't render with a lot of dead vertical space."""
    positions: list[tuple[int, int]] = []
    for i in range(count):
        row = i // _MAX_PER_ROW
        col = i % _MAX_PER_ROW
        per_this_row = min(_MAX_PER_ROW, count - row * _MAX_PER_ROW)
        row_width = per_this_row * _NODE_WIDTH + (per_this_row - 1) * 80
        row_left = (_CANVAS_WIDTH - row_width) // 2
        row_top = _CANVAS_MARGIN + row * (_NODE_HEIGHT + _ROW_GAP)
        x = row_left + col * (_NODE_WIDTH + 80)
        positions.append((x, row_top))
    return positions


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build_diagram_svg(nodes: list[DiagramNode], edges: list[DiagramEdge]) -> tuple[str, int, int]:
    """Deterministically lays out and draws an SVG diagram from structured
    node/edge data — the LLM never generates markup or coordinates, only
    labels and which node connects to which, so a diagram can never come out
    with invalid XML, off-palette colors, or overlapping shapes the way
    trusting a model to hand-write SVG could. Returns (svg, width, height) —
    the caller needs the pixel dimensions to size the embedded picture at
    the right aspect ratio."""
    rows = -(-len(nodes) // _MAX_PER_ROW) if nodes else 1
    height = _canvas_height(rows)
    positions = _node_positions(len(nodes))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_CANVAS_WIDTH}" height="{height}" '
        f'viewBox="0 0 {_CANVAS_WIDTH} {height}">',
        f'<rect x="0" y="0" width="{_CANVAS_WIDTH}" height="{height}" fill="{_BACKGROUND}"/>',
        "<defs><marker id='arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' "
        f"orient='auto-start-reverse'><path d='M0,0 L10,5 L0,10 z' fill='{_ACCENT_A}'/></marker></defs>",
    ]

    centers = [(x + _NODE_WIDTH / 2, y + _NODE_HEIGHT / 2) for x, y in positions]

    for edge in edges:
        if edge.from_index >= len(nodes) or edge.to_index >= len(nodes) or edge.from_index == edge.to_index:
            continue
        fx, fy = centers[edge.from_index]
        tx, ty = centers[edge.to_index]
        # Trim the line to the node boundary rather than its center, so the
        # arrowhead lands at the box edge instead of overlapping the text.
        dx, dy = tx - fx, ty - fy
        length = max((dx**2 + dy**2) ** 0.5, 1)
        pad = _NODE_WIDTH / 2 + 4
        start_x, start_y = fx + dx / length * pad, fy + dy / length * pad
        end_x, end_y = tx - dx / length * pad, ty - dy / length * pad
        parts.append(
            f'<line x1="{start_x:.0f}" y1="{start_y:.0f}" x2="{end_x:.0f}" y2="{end_y:.0f}" '
            f'stroke="{_ACCENT_A}" stroke-width="3" marker-end="url(#arrow)"/>'
        )
        if edge.label:
            # Offset above the line rather than boxed on top of it — a
            # background box wide enough to read cleanly can fully cover a
            # short line between adjacent nodes (the line/arrowhead would
            # render underneath it, invisibly); an offset label never has
            # that failure mode regardless of how short the segment is.
            mid_x, mid_y = (start_x + end_x) / 2, (start_y + end_y) / 2
            parts.append(
                f'<text x="{mid_x:.0f}" y="{mid_y - 12:.0f}" font-family="Calibri" font-size="15" '
                f'fill="{_MUTED}" text-anchor="middle">{_escape(edge.label)}</text>'
            )

    for node, (x, y) in zip(nodes, positions, strict=True):
        parts.append(
            f'<rect x="{x}" y="{y}" width="{_NODE_WIDTH}" height="{_NODE_HEIGHT}" rx="10" '
            f'fill="none" stroke="{_ACCENT_A}" stroke-width="3"/>'
        )
        parts.append(
            f'<text x="{x + _NODE_WIDTH / 2:.0f}" y="{y + _NODE_HEIGHT / 2 + 7:.0f}" '
            f'font-family="Georgia" font-size="20" font-weight="bold" fill="{_INK}" '
            f'text-anchor="middle">{_escape(node.label)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts), _CANVAS_WIDTH, height


def render_diagram_png(svg: str) -> bytes:
    """Rasterizes SVG to PNG bytes via resvg (a self-contained compiled
    wheel — no system Cairo/GTK dependency to install on a deploy host,
    unlike cairosvg), so python-pptx can embed it as a picture; python-pptx
    has no native SVG support and requires a raster format it can read
    dimensions from."""
    return bytes(resvg_py.svg_to_bytes(svg_string=svg))
