from xml.etree import ElementTree
from typing import List, Optional
from dataclasses import dataclass
from copy import deepcopy

from svg_to_gcode.svg_parser import Path, Transformation
from svg_to_gcode.svg_parser._shapes import shape_to_path_d, is_text_element, is_basic_shape
from svg_to_gcode.geometry import Curve

NAMESPACES = {'svg': 'http://www.w3.org/2000/svg',
              'inkscape': 'http://www.inkscape.org/namespaces/inkscape'}


def _is_element(element: ElementTree.Element) -> bool:
    """Return True if node is a regular XML element (filters out lxml comments/PIs)."""
    return isinstance(getattr(element, "tag", None), str)


def _has_style(element: ElementTree.Element, key: str, value: str) -> bool:
    """
    Check if an element contains a specific key and value either as an independent attribute or in the style attribute.
    """
    if not _is_element(element):
        return False
    return element.get(key) == value or (element.get("style") and f"{key}:{value}" in element.get("style"))


def _is_layer(element: ElementTree.Element) -> bool:
    """Check if element is an Inkscape layer (group with inkscape:groupmode='layer')."""
    if not _is_element(element):
        return False
    return element.tag == "{%s}g" % NAMESPACES["svg"] and \
           element.get("{%s}groupmode" % NAMESPACES["inkscape"]) == "layer"


def _is_debug_layer(element: ElementTree.Element) -> bool:
    """Check if element is a debug layer to be excluded."""
    if not _is_element(element):
        return False
    layer_id = element.get("id", "")
    return layer_id in ("debug_traces", "debug_references")


def _get_layer_label(element: ElementTree.Element) -> str:
    """Get layer label from inkscape:label or fall back to id."""
    return element.get("{%s}label" % NAMESPACES["inkscape"]) or element.get("id", "")


def _parse_element_curves(element: ElementTree.Element, canvas_height: float,
                           transform_origin: bool, transformation: Optional[Transformation],
                           draw_hidden: bool) -> List[Curve]:
    """
    Parse curves from a single element (path or basic shape).
    Returns list of curves (empty if element not drawable or not a supported type).
    """
    curves = []
    if not _is_element(element):
        return curves
    
    # Check display="none" - cannot be overridden
    if _has_style(element, "display", "none"):
        return curves
    
    # Skip defs
    if element.tag == "{%s}defs" % NAMESPACES["svg"]:
        return curves
    
    # Visibility check
    visible = not (_has_style(element, "visibility", "hidden")
                   or _has_style(element, "visibility", "collapse"))
    visible = visible or _has_style(element, "visibility", "visible")
    
    if not (draw_hidden or visible):
        return curves
    
    # Parse <path> elements
    if element.tag == "{%s}path" % NAMESPACES["svg"]:
        d = element.get('d', '')
        if d:
            path = Path(d, canvas_height, transform_origin, transformation)
            curves.extend(path.curves)
    
    # Parse basic shapes
    elif is_basic_shape(element):
        d = shape_to_path_d(element)
        if d:
            path = Path(d, canvas_height, transform_origin, transformation)
            curves.extend(path.curves)
    
    return curves


def _collect_text_count(element: ElementTree.Element) -> int:
    """Recursively count <text> elements in subtree (excluding display=none and sublayers)."""
    if not _is_element(element):
        return 0
    if _has_style(element, "display", "none") or element.tag == "{%s}defs" % NAMESPACES["svg"]:
        return 0
    count = 1 if is_text_element(element) else 0
    for child in element:
        if not _is_element(child) or _is_layer(child):
            continue
        count += _collect_text_count(child)
    return count


# Todo deal with viewBoxes
def parse_root(root: ElementTree.Element, transform_origin=True, canvas_height=None, draw_hidden=False,
               visible_root=True, root_transformation=None) -> List[Curve]:
    """
    Recursively parse an etree root's children into geometric curves.

    :param root: The etree element who's children should be recursively parsed. The root will not be drawn.
    :param canvas_height: The height of the canvas. By default the height attribute of the root is used. If the root
    does not contain the height attribute, it must be either manually specified or transform must be False.
    :param transform_origin: Whether or not to transform input coordinates from the svg coordinate system to standard
    cartesian system. Depends on canvas_height for calculations.
    :param draw_hidden: Whether or not to draw hidden elements based on their display, visibility and opacity attributes.
    :param visible_root: Specifies whether or the root is visible. (Inheritance can be overridden)
    :param root_transformation: Specifies whether the root's transformation. (Transformations are inheritable)
    :return: A list of geometric curves describing the svg. Use the Compiler sub-module to compile them to gcode.
    """

    if canvas_height is None:
        height_str = root.get("height")
        canvas_height = float(height_str) if height_str.isnumeric() else float(height_str[:-2])

    curves = []

    # Draw visible elements (Depth-first search)
    for element in list(root):
        if not _is_element(element):
            continue

        # display cannot be overridden by inheritance. Just skip the element
        display = _has_style(element, "display", "none")

        if display or element.tag == "{%s}defs" % NAMESPACES["svg"]:
            continue

        transformation = deepcopy(root_transformation) if root_transformation else None

        transform = element.get('transform')
        if transform:
            transformation = Transformation() if transformation is None else transformation
            transformation.add_transform(transform)

        # Is the element and it's root not hidden?
        visible = visible_root and not (_has_style(element, "visibility", "hidden")
                                        or _has_style(element, "visibility", "collapse"))
        # Override inherited visibility
        visible = visible or (_has_style(element, "visibility", "visible"))

        # If the current element is opaque and visible, draw it
        if draw_hidden or visible:
            curves.extend(_parse_element_curves(element, canvas_height, transform_origin, transformation, draw_hidden))

        # Continue the recursion
        curves.extend(parse_root(element, transform_origin, canvas_height, draw_hidden, visible, transformation))

    return curves


@dataclass
class LayerData:
    """
    Data container for a single layer's parsed content.
    
    :param layer_id: The SVG id attribute of the layer group.
    :param label: The inkscape:label (display name) or id if label not present.
    :param visible: Whether the layer is visible (display != none, visibility != hidden/collapse).
    :param curves: List of geometric curves parsed from this layer.
    :param unconverted_text_count: Number of <text> elements in this layer that were not converted to paths.
    """
    layer_id: str
    label: str
    visible: bool
    curves: List[Curve]
    unconverted_text_count: int = 0


def _collect_curves_in_subtree(element: ElementTree.Element, canvas_height: float,
                               transform_origin: bool, parent_transformation: Optional[Transformation],
                               draw_hidden: bool, parent_visible: bool) -> List[Curve]:
    """Recursively collect curves from an element and its non-layer descendants."""
    if not _is_element(element) or _is_layer(element):
        return []
    if _has_style(element, "display", "none") or element.tag == "{%s}defs" % NAMESPACES["svg"]:
        return []

    transformation = deepcopy(parent_transformation) if parent_transformation else None
    transform = element.get('transform')
    if transform:
        transformation = Transformation() if transformation is None else transformation
        transformation.add_transform(transform)

    visible = parent_visible and not (_has_style(element, "visibility", "hidden")
                                      or _has_style(element, "visibility", "collapse"))
    visible = visible or _has_style(element, "visibility", "visible")

    curves = []
    if draw_hidden or visible:
        curves.extend(_parse_element_curves(element, canvas_height, transform_origin, transformation, draw_hidden))

    for child in list(element):
        curves.extend(_collect_curves_in_subtree(
            child, canvas_height, transform_origin, transformation, draw_hidden, visible
        ))
    return curves


def _parse_layer_recursive(layer_element: ElementTree.Element, canvas_height: float,
                            transform_origin: bool, parent_transformation: Optional[Transformation],
                            draw_hidden: bool, parent_visible: bool) -> LayerData:
    """
    Recursively parse a single layer element and its sublayers.
    Returns LayerData for this layer (sublayers are NOT included - they are handled by parse_layers).
    """
    # Compute layer visibility
    display_none = _has_style(layer_element, "display", "none")
    visibility_hidden = _has_style(layer_element, "visibility", "hidden") \
                        or _has_style(layer_element, "visibility", "collapse")
    visibility_visible = _has_style(layer_element, "visibility", "visible")
    
    # Layer's own visibility (display=none overrides everything)
    layer_visible = not display_none and (parent_visible and not visibility_hidden or visibility_visible)
    
    # Compute transformation
    transformation = deepcopy(parent_transformation) if parent_transformation else None
    transform = layer_element.get('transform')
    if transform:
        transformation = Transformation() if transformation is None else transformation
        transformation.add_transform(transform)
    
    # Collect curves from direct children and nested non-layer groups
    curves = []
    for element in list(layer_element):
        if not _is_element(element) or _is_layer(element):
            # Non-elements (comments) and sublayers are skipped here
            continue
        curves.extend(_collect_curves_in_subtree(
            element, canvas_height, transform_origin, transformation, draw_hidden, True
        ))
    
    # Count text elements in this layer (excluding sublayers)
    text_count = 0
    for element in list(layer_element):
        if not _is_element(element) or _is_layer(element):
            continue
        text_count += _collect_text_count(element)
    
    return LayerData(
        layer_id=layer_element.get("id", ""),
        label=_get_layer_label(layer_element),
        visible=layer_visible,
        curves=curves,
        unconverted_text_count=text_count
    )


def _collect_all_layers(element: ElementTree.Element, parent_transformation: Optional[Transformation],
                                 parent_visible: bool, canvas_height: float, transform_origin: bool,
                                 draw_hidden: bool, layers_list: List[LayerData],
                                 root_transformation: Optional[Transformation]):
    """
    Recursively collect all layers (including nested sublayers) into layers_list.
    """
    for child in list(element):
        if _is_layer(child):
            if not _is_debug_layer(child):
                # Parse this layer with inherited transformation and visibility
                layer_data = _parse_layer_recursive(child, canvas_height, transform_origin,
                                                     parent_transformation, draw_hidden, parent_visible)
                layers_list.append(layer_data)
                # Recursively process sublayers with this layer's transformation/visibility
                # Compute this layer's transformation for passing to children
                layer_trans = deepcopy(parent_transformation) if parent_transformation else None
                transform = child.get('transform')
                if transform:
                    layer_trans = Transformation() if layer_trans is None else layer_trans
                    layer_trans.add_transform(transform)
                
                # Compute this layer's visibility
                display_none = _has_style(child, "display", "none")
                visibility_hidden = _has_style(child, "visibility", "hidden") \
                                    or _has_style(child, "visibility", "collapse")
                visibility_visible = _has_style(child, "visibility", "visible")
                layer_visible = not display_none and (parent_visible and not visibility_hidden or visibility_visible)
                
                _collect_all_layers(child, layer_trans, layer_visible, canvas_height, transform_origin,
                                    draw_hidden, layers_list, root_transformation)


def parse_layers(root: ElementTree.Element, transform_origin=True, canvas_height=None, draw_hidden=False,
                 root_transformation=None, order: str = "top_to_bottom") -> List[LayerData]:
    """
    Parse SVG document into layer-separated curve lists.

    :param root: The SVG root element.
    :param transform_origin: Whether to transform from SVG (top-left origin) to Cartesian (bottom-left).
    :param canvas_height: Canvas height for coordinate transformation. If None, extracted from root.
    :param draw_hidden: Whether to include hidden elements (display=none, visibility=hidden).
    :param root_transformation: Base transformation to apply (e.g., from laser.py offsets/scaling).
    :param order: Layer ordering - "top_to_bottom" (Inkscape panel top first, DOM reversed) 
                  or "bottom_to_top" (DOM order, bottom layer first).
    :return: List of LayerData objects, ordered per `order` parameter.
    """
    if canvas_height is None:
        height_str = root.get("height")
        canvas_height = float(height_str) if height_str.isnumeric() else float(height_str[:-2])

    layers_data = []
    root_elements_curves = []
    root_text_count = 0
    
    # Process root-level elements (not in any layer)
    for element in list(root):
        if not _is_element(element) or _is_layer(element):
            # Non-elements (comments) and layers are handled separately
            pass
        elif element.tag != "{%s}defs" % NAMESPACES["svg"]:
            # Root-level elements (not in any layer)
            root_elements_curves.extend(
                _collect_curves_in_subtree(
                    element, canvas_height, transform_origin, root_transformation, draw_hidden, True
                )
            )
            root_text_count += _collect_text_count(element)
    
    # Recursively collect all layers (including nested sublayers)
    _collect_all_layers(root, root_transformation, True, canvas_height, transform_origin,
                        draw_hidden, layers_data, root_transformation)
    
    # Add root elements as a virtual layer if any exist
    if root_elements_curves or root_text_count > 0:
        root_layer = LayerData(
            layer_id="__root__",
            label="(Root Elements)",
            visible=True,
            curves=root_elements_curves,
            unconverted_text_count=root_text_count
        )
        layers_data.append(root_layer)
    
    # Apply ordering
    if order == "top_to_bottom":
        # Inkscape panel shows top layer first = DOM last
        # So we reverse the DOM order
        layers_data = list(reversed(layers_data))
    elif order == "bottom_to_top":
        # DOM order = bottom layer first
        pass
    else:
        raise ValueError(f"Invalid order: {order}. Use 'top_to_bottom' or 'bottom_to_top'.")
    
    return layers_data


def parse_string(svg_string: str, transform_origin=True, canvas_height=None, draw_hidden=False) -> List[Curve]:
    """
        Recursively parse an svg string into geometric curves. (Wrapper for parse_root)

        :param svg_string: The etree element who's children should be recursively parsed. The root will not be drawn.
        :param canvas_height: The height of the canvas. By default the height attribute of the root is used. If the root
        does not contain the height attribute, it must be either manually specified or transform_origin must be False.
        :param transform_origin: Whether or not to transform input coordinates from the svg coordinate system to standard cartesian
         system. Depends on canvas_height for calculations.
        :param draw_hidden: Whether or not to draw hidden elements based on their display, visibility and opacity attributes.
        :return: A list of geometric curves describing the svg. Use the Compiler sub-module to compile them to gcode.
    """
    root = ElementTree.fromstring(svg_string)
    return parse_root(root, transform_origin, canvas_height, draw_hidden)


def parse_file(file_path: str, transform_origin=True, canvas_height=None, draw_hidden=False) -> List[Curve]:
    """
            Recursively parse an svg file into geometric curves. (Wrapper for parse_root)

            :param file_path: The etree element who's children should be recursively parsed. The root will not be drawn.
            :param canvas_height: The height of the canvas. By default the height attribute of the root is used. If the root
            does not contain the height attribute, it must be either manually specified or transform_origin must be False.
            :param transform_origin: Whether or not to transform input coordinates from the svg coordinate system to standard cartesian
             system. Depends on canvas_height for calculations.
            :param draw_hidden: Whether or not to draw hidden elements based on their display, visibility and opacity attributes.
            :return: A list of geometric curves describing the svg. Use the Compiler sub-module to compile them to gcode.
        """
    root = ElementTree.parse(file_path).getroot()
    return parse_root(root, transform_origin, canvas_height, draw_hidden)
