"""
SVG basic shapes to path 'd' attribute converter.

This module converts SVG basic shape elements (<rect>, <circle>, <ellipse>,
<line>, <polyline>, <polygon>) into equivalent SVG path data strings
that can be parsed by the existing Path class.

Circular and elliptical arcs are approximated using 4-segment cubic Bezier
curves (kappa ≈ 0.5522847498) to avoid the known EllipticalArc transformation bug.
"""

import math
from typing import Optional, List, Tuple
from xml.etree import ElementTree

NAMESPACES = {'svg': 'http://www.w3.org/2000/svg'}

# Kappa constant for cubic Bezier approximation of a quarter circle
# Derived from: kappa = 4/3 * (sqrt(2) - 1) ≈ 0.5522847498307936
KAPPA = 4.0 / 3.0 * (math.sqrt(2.0) - 1.0)


def _parse_points(points_str: str) -> List[Tuple[float, float]]:
    """Parse SVG points attribute string into list of (x, y) tuples."""
    points = []
    tokens = points_str.replace(',', ' ').split()
    for i in range(0, len(tokens), 2):
        if i + 1 < len(tokens):
            x = float(tokens[i])
            y = float(tokens[i + 1])
            points.append((x, y))
    return points


def _format_coord(val: float) -> str:
    """Format coordinate, avoiding scientific notation for small values."""
    if abs(val) < 1e-10:
        return "0"
    return f"{val:.10f}".rstrip('0').rstrip('.')


def rect_to_path_d(x: float, y: float, width: float, height: float,
                    rx: float = 0.0, ry: float = 0.0) -> str:
    """
    Convert <rect> to path data.
    
    SVG spec: rx and ry are clamped to half of width/height respectively.
    If width <= 0 or height <= 0, returns empty string (no rendering).
    """
    if width <= 0 or height <= 0:
        return ""
    
    # Clamp rx, ry per SVG spec
    rx = min(rx, width / 2.0) if rx > 0 else 0.0
    ry = min(ry, height / 2.0) if ry > 0 else 0.0
    
    # If no rounding, simple rectangle
    if rx == 0 and ry == 0:
        x2 = x + width
        y2 = y + height
        return f"M {_format_coord(x)} {_format_coord(y)} " \
               f"L {_format_coord(x2)} {_format_coord(y)} " \
               f"L {_format_coord(x2)} {_format_coord(y2)} " \
               f"L {_format_coord(x)} {_format_coord(y2)} Z"
    
    # Rounded rectangle using 4 cubic Bezier segments for corners
    x2 = x + width
    y2 = y + height
    
    # Corner control point offsets
    krx = rx * KAPPA
    kry = ry * KAPPA
    
    parts = [
        f"M {_format_coord(x + rx)} {_format_coord(y)}",
        # Top edge
        f"L {_format_coord(x2 - rx)} {_format_coord(y)}",
        # Top-right corner
        f"C {_format_coord(x2 - rx + krx)} {_format_coord(y)} "
          f"{_format_coord(x2)} {_format_coord(y + ry - kry)} "
          f"{_format_coord(x2)} {_format_coord(y + ry)}",
        # Right edge
        f"L {_format_coord(x2)} {_format_coord(y2 - ry)}",
        # Bottom-right corner
        f"C {_format_coord(x2)} {_format_coord(y2 - ry + kry)} "
          f"{_format_coord(x2 - rx + krx)} {_format_coord(y2)} "
          f"{_format_coord(x2 - rx)} {_format_coord(y2)}",
        # Bottom edge
        f"L {_format_coord(x + rx)} {_format_coord(y2)}",
        # Bottom-left corner
        f"C {_format_coord(x + rx - krx)} {_format_coord(y2)} "
          f"{_format_coord(x)} {_format_coord(y2 - ry + kry)} "
          f"{_format_coord(x)} {_format_coord(y2 - ry)}",
        # Left edge
        f"L {_format_coord(x)} {_format_coord(y + ry)}",
        # Top-left corner
        f"C {_format_coord(x)} {_format_coord(y + ry - kry)} "
          f"{_format_coord(x + rx - krx)} {_format_coord(y)} "
          f"{_format_coord(x + rx)} {_format_coord(y)} Z"
    ]
    return " ".join(parts)


def circle_to_path_d(cx: float, cy: float, r: float) -> str:
    """
    Convert <circle> to path data using 4 cubic Bezier segments.
    """
    if r <= 0:
        return ""
    
    kr = r * KAPPA
    
    parts = [
        f"M {_format_coord(cx)} {_format_coord(cy - r)}",
        # Top-right quadrant
        f"C {_format_coord(cx + kr)} {_format_coord(cy - r)} "
          f"{_format_coord(cx + r)} {_format_coord(cy - kr)} "
          f"{_format_coord(cx + r)} {_format_coord(cy)}",
        # Bottom-right quadrant
        f"C {_format_coord(cx + r)} {_format_coord(cy + kr)} "
          f"{_format_coord(cx + kr)} {_format_coord(cy + r)} "
          f"{_format_coord(cx)} {_format_coord(cy + r)}",
        # Bottom-left quadrant
        f"C {_format_coord(cx - kr)} {_format_coord(cy + r)} "
          f"{_format_coord(cx - r)} {_format_coord(cy + kr)} "
          f"{_format_coord(cx - r)} {_format_coord(cy)}",
        # Top-left quadrant
        f"C {_format_coord(cx - r)} {_format_coord(cy - kr)} "
          f"{_format_coord(cx - kr)} {_format_coord(cy - r)} "
          f"{_format_coord(cx)} {_format_coord(cy - r)} Z"
    ]
    return " ".join(parts)


def ellipse_to_path_d(cx: float, cy: float, rx: float, ry: float) -> str:
    """
    Convert <ellipse> to path data using 4 cubic Bezier segments.
    """
    if rx <= 0 or ry <= 0:
        return ""
    
    krx = rx * KAPPA
    kry = ry * KAPPA
    
    parts = [
        f"M {_format_coord(cx)} {_format_coord(cy - ry)}",
        # Top-right quadrant
        f"C {_format_coord(cx + krx)} {_format_coord(cy - ry)} "
          f"{_format_coord(cx + rx)} {_format_coord(cy - kry)} "
          f"{_format_coord(cx + rx)} {_format_coord(cy)}",
        # Bottom-right quadrant
        f"C {_format_coord(cx + rx)} {_format_coord(cy + kry)} "
          f"{_format_coord(cx + krx)} {_format_coord(cy + ry)} "
          f"{_format_coord(cx)} {_format_coord(cy + ry)}",
        # Bottom-left quadrant
        f"C {_format_coord(cx - krx)} {_format_coord(cy + ry)} "
          f"{_format_coord(cx - rx)} {_format_coord(cy + kry)} "
          f"{_format_coord(cx - rx)} {_format_coord(cy)}",
        # Top-left quadrant
        f"C {_format_coord(cx - rx)} {_format_coord(cy - kry)} "
          f"{_format_coord(cx - krx)} {_format_coord(cy - ry)} "
          f"{_format_coord(cx)} {_format_coord(cy - ry)} Z"
    ]
    return " ".join(parts)


def line_to_path_d(x1: float, y1: float, x2: float, y2: float) -> str:
    """Convert <line> to path data."""
    return f"M {_format_coord(x1)} {_format_coord(y1)} L {_format_coord(x2)} {_format_coord(y2)}"


def polyline_to_path_d(points: List[Tuple[float, float]], close: bool = False) -> str:
    """Convert <polyline> or <polygon> to path data."""
    if not points:
        return ""
    
    parts = [f"M {_format_coord(points[0][0])} {_format_coord(points[0][1])}"]
    for x, y in points[1:]:
        parts.append(f"L {_format_coord(x)} {_format_coord(y)}")
    if close:
        parts.append("Z")
    return " ".join(parts)


def _local_tag(element: ElementTree.Element) -> Optional[str]:
    """Return local SVG tag name, or None for non-element nodes (e.g. lxml comments/PIs)."""
    tag = getattr(element, 'tag', None)
    if not isinstance(tag, str):
        return None
    return tag.split('}')[-1] if '}' in tag else tag


def shape_to_path_d(element: ElementTree.Element) -> Optional[str]:
    """
    Convert an SVG basic shape element to equivalent path 'd' attribute string.
    
    Returns None if the element is not a supported basic shape or has invalid geometry.
    """
    tag = _local_tag(element)
    if tag is None:
        return None
    
    try:
        if tag == 'rect':
            x = float(element.get('x', '0'))
            y = float(element.get('y', '0'))
            width = float(element.get('width', '0'))
            height = float(element.get('height', '0'))
            rx = float(element.get('rx', '0')) if element.get('rx') is not None else 0.0
            ry = float(element.get('ry', '0')) if element.get('ry') is not None else 0.0
            # SVG spec: if only one of rx/ry is specified, the other takes the same value
            if element.get('rx') is not None and element.get('ry') is None:
                ry = rx
            elif element.get('ry') is not None and element.get('rx') is None:
                rx = ry
            return rect_to_path_d(x, y, width, height, rx, ry)
        
        elif tag == 'circle':
            cx = float(element.get('cx', '0'))
            cy = float(element.get('cy', '0'))
            r = float(element.get('r', '0'))
            return circle_to_path_d(cx, cy, r)
        
        elif tag == 'ellipse':
            cx = float(element.get('cx', '0'))
            cy = float(element.get('cy', '0'))
            rx = float(element.get('rx', '0'))
            ry = float(element.get('ry', '0'))
            return ellipse_to_path_d(cx, cy, rx, ry)
        
        elif tag == 'line':
            x1 = float(element.get('x1', '0'))
            y1 = float(element.get('y1', '0'))
            x2 = float(element.get('x2', '0'))
            y2 = float(element.get('y2', '0'))
            return line_to_path_d(x1, y1, x2, y2)
        
        elif tag == 'polyline':
            points_str = element.get('points', '')
            points = _parse_points(points_str)
            return polyline_to_path_d(points, close=False)
        
        elif tag == 'polygon':
            points_str = element.get('points', '')
            points = _parse_points(points_str)
            return polyline_to_path_d(points, close=True)
        
    except (ValueError, TypeError) as e:
        # Invalid attribute values
        return None
    
    return None


def is_text_element(element: ElementTree.Element) -> bool:
    """Check if element is an SVG <text> element."""
    return _local_tag(element) == 'text'


def is_basic_shape(element: ElementTree.Element) -> bool:
    """Check if element is a supported basic shape."""
    return _local_tag(element) in ('rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon')