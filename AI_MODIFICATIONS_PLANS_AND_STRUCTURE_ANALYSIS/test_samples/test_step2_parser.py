#!/usr/bin/env python3
"""
Unit tests for Step 2: Multi-layer parser with basic shapes support.
Tests svg_to_gcode.svg_parser._parser_methods.parse_layers and basic shape conversion.
"""

import unittest
import tempfile
import os
from xml.etree import ElementTree

from svg_to_gcode.svg_parser import parse_layers, parse_root, parse_string, LayerData
from svg_to_gcode.svg_parser._shapes import (
    shape_to_path_d, rect_to_path_d, circle_to_path_d, ellipse_to_path_d,
    line_to_path_d, polyline_to_path_d, is_text_element, is_basic_shape
)
from svg_to_gcode.geometry import Line, CubicBazier


# Test SVG with multiple layers, basic shapes, text, and debug layers
TEST_SVG_MULTI_LAYER = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="300mm" height="300mm" viewBox="0 0 300 300" xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
  <defs></defs>
  <g id="layer1" inkscape:groupmode="layer" inkscape:label="Bottom Layer">
    <rect x="10" y="10" width="50" height="50" fill="none" stroke="black"/>
  </g>
  <g id="layer2" inkscape:groupmode="layer" inkscape:label="Middle Layer">
    <circle cx="100" cy="100" r="30" fill="none" stroke="black"/>
  </g>
  <g id="layer3" inkscape:groupmode="layer" inkscape:label="Top Layer" style="display:none">
    <ellipse cx="200" cy="200" rx="40" ry="20" fill="none" stroke="black"/>
  </g>
  <g id="debug_traces" inkscape:groupmode="layer" inkscape:label="debug traces">
    <path d="M 0 0 L 100 100" stroke="red"/>
  </g>
  <g id="layer4" inkscape:groupmode="layer" inkscape:label="Cut Layer">
    <line x1="50" y1="50" x2="150" y2="150" stroke="black"/>
    <text x="60" y="60">Test Text</text>
  </g>
  <g id="layer5" inkscape:groupmode="layer" inkscape:label="Sublayer Parent" transform="translate(10,10)">
    <rect x="0" y="0" width="20" height="20" fill="red"/>
    <g id="layer5_sublayer" inkscape:groupmode="layer" inkscape:label="Sublayer Child">
      <circle cx="10" cy="10" r="5" fill="blue"/>
    </g>
  </g>
  <rect x="250" y="250" width="30" height="30" fill="green"/>  <!-- Root element -->
</svg>
'''


# Test SVG for basic shapes
TEST_SVG_SHAPES = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="200mm" height="200mm" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
  <rect x="10" y="10" width="50" height="40" fill="none" stroke="black"/>
  <rect x="70" y="10" width="50" height="40" rx="5" ry="5" fill="none" stroke="black"/>
  <circle cx="100" cy="100" r="30" fill="none" stroke="black"/>
  <ellipse cx="150" cy="150" rx="40" ry="20" fill="none" stroke="black"/>
  <line x1="10" y1="180" x2="190" y2="180" stroke="black"/>
  <polyline points="10,10 50,10 50,50 10,50" fill="none" stroke="black"/>
  <polygon points="100,10 140,10 140,40 100,40" fill="none" stroke="black"/>
</svg>
'''


class TestShapesConversion(unittest.TestCase):
    """Test basic shape to path data conversion."""
    
    def test_rect_simple(self):
        d = rect_to_path_d(10, 10, 50, 40)
        self.assertIn("M 10 10", d)
        self.assertIn("L 60 10", d)
        self.assertIn("L 60 50", d)
        self.assertIn("L 10 50", d)
        self.assertIn("Z", d)
    
    def test_rect_rounded(self):
        d = rect_to_path_d(10, 10, 50, 40, 5, 5)
        self.assertIn("C", d)  # Cubic Bezier for rounded corners
        self.assertIn("Z", d)
    
    def test_rect_zero_size(self):
        d = rect_to_path_d(10, 10, 0, 40)
        self.assertEqual(d, "")
        d = rect_to_path_d(10, 10, 50, 0)
        self.assertEqual(d, "")
    
    def test_rect_rx_clamping(self):
        # rx > width/2 should be clamped
        d = rect_to_path_d(0, 0, 10, 10, 100, 0)
        self.assertIn("C", d)  # Should still produce valid path
    
    def test_circle(self):
        d = circle_to_path_d(100, 100, 30)
        self.assertIn("M 100 70", d)
        self.assertIn("C", d)
        self.assertEqual(d.count("C"), 4)  # 4 quadrants
        self.assertIn("Z", d)
    
    def test_circle_zero_radius(self):
        d = circle_to_path_d(100, 100, 0)
        self.assertEqual(d, "")
    
    def test_ellipse(self):
        d = ellipse_to_path_d(150, 150, 40, 20)
        self.assertIn("M 150 130", d)
        self.assertIn("C", d)
        self.assertEqual(d.count("C"), 4)
        self.assertIn("Z", d)
    
    def test_line(self):
        d = line_to_path_d(10, 10, 100, 100)
        self.assertEqual(d, "M 10 10 L 100 100")
    
    def test_polyline(self):
        points = [(10, 10), (50, 10), (50, 50), (10, 50)]
        d = polyline_to_path_d(points, close=False)
        self.assertIn("M 10 10", d)
        self.assertIn("L 50 10", d)
        self.assertIn("L 50 50", d)
        self.assertIn("L 10 50", d)
        self.assertNotIn("Z", d)
    
    def test_polygon(self):
        points = [(10, 10), (50, 10), (50, 50), (10, 50)]
        d = polyline_to_path_d(points, close=True)
        self.assertIn("Z", d)
    
    def test_shape_to_path_d_rect(self):
        elem = ElementTree.fromstring('<rect x="10" y="10" width="50" height="40"/>')
        d = shape_to_path_d(elem)
        self.assertIsNotNone(d)
        self.assertIn("M 10 10", d)
    
    def test_shape_to_path_d_circle(self):
        elem = ElementTree.fromstring('<circle cx="100" cy="100" r="30"/>')
        d = shape_to_path_d(elem)
        self.assertIsNotNone(d)
        self.assertIn("M 100 70", d)
    
    def test_shape_to_path_d_ellipse(self):
        elem = ElementTree.fromstring('<ellipse cx="150" cy="150" rx="40" ry="20"/>')
        d = shape_to_path_d(elem)
        self.assertIsNotNone(d)
        self.assertIn("M 150 130", d)
    
    def test_shape_to_path_d_line(self):
        elem = ElementTree.fromstring('<line x1="10" y1="10" x2="100" y2="100"/>')
        d = shape_to_path_d(elem)
        self.assertIsNotNone(d)
        self.assertEqual(d, "M 10 10 L 100 100")
    
    def test_shape_to_path_d_polyline(self):
        elem = ElementTree.fromstring('<polyline points="10,10 50,10 50,50"/>')
        d = shape_to_path_d(elem)
        self.assertIsNotNone(d)
        self.assertIn("M 10 10", d)
        self.assertNotIn("Z", d)
    
    def test_shape_to_path_d_polygon(self):
        elem = ElementTree.fromstring('<polygon points="10,10 50,10 50,50"/>')
        d = shape_to_path_d(elem)
        self.assertIsNotNone(d)
        self.assertIn("Z", d)
    
    def test_is_text_element(self):
        elem = ElementTree.fromstring('<text x="10" y="10">Hello</text>')
        self.assertTrue(is_text_element(elem))
        elem = ElementTree.fromstring('<rect x="10" y="10" width="10" height="10"/>')
        self.assertFalse(is_text_element(elem))
    
    def test_is_basic_shape(self):
        for tag in ['rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon']:
            elem = ElementTree.fromstring(f'<{tag} x="0" y="0" width="10" height="10" r="5" rx="5" ry="5" cx="5" cy="5" x1="0" y1="0" x2="10" y2="10" points="0,0 10,10"/>')
            self.assertTrue(is_basic_shape(elem), f"Failed for {tag}")
        elem = ElementTree.fromstring('<path d="M 0 0 L 10 10"/>')
        self.assertFalse(is_basic_shape(elem))
        elem = ElementTree.fromstring('<text x="10" y="10">Hello</text>')
        self.assertFalse(is_basic_shape(elem))


class TestParseLayers(unittest.TestCase):
    """Test parse_layers function."""
    
    def setUp(self):
        self.root = ElementTree.fromstring(TEST_SVG_MULTI_LAYER)
    
    def test_layer_count(self):
        layers = parse_layers(self.root, canvas_height=300, order="top_to_bottom")
        # 5 regular layers (layer1-5) + 1 sublayer + 1 root element layer = 7
        # debug_traces should be excluded
        self.assertEqual(len(layers), 7)
    
    def test_layer_order_top_to_bottom(self):
        layers = parse_layers(self.root, canvas_height=300, order="top_to_bottom")
        # Flat reverse of DOM order (parent before child in DOM)
        # DOM order: layer1, layer2, layer3, layer4, layer5, layer5_sublayer, root
        # Reversed: root, layer5_sublayer, layer5, layer4, layer3, layer2, layer1
        labels = [l.label for l in layers]
        self.assertEqual(labels[0], "(Root Elements)")
        self.assertEqual(labels[1], "Sublayer Child")
        self.assertEqual(labels[2], "Sublayer Parent")
        self.assertEqual(labels[3], "Cut Layer")
        self.assertEqual(labels[4], "Top Layer")
        self.assertEqual(labels[5], "Middle Layer")
        self.assertEqual(labels[6], "Bottom Layer")
    
    def test_layer_order_bottom_to_top(self):
        layers = parse_layers(self.root, canvas_height=300, order="bottom_to_top")
        # DOM order (parent before child)
        labels = [l.label for l in layers]
        self.assertEqual(labels[0], "Bottom Layer")
        self.assertEqual(labels[1], "Middle Layer")
        self.assertEqual(labels[2], "Top Layer")
        self.assertEqual(labels[3], "Cut Layer")
        self.assertEqual(labels[4], "Sublayer Parent")
        self.assertEqual(labels[5], "Sublayer Child")
        self.assertEqual(labels[6], "(Root Elements)")
    
    def test_debug_layer_excluded(self):
        layers = parse_layers(self.root, canvas_height=300)
        ids = [l.layer_id for l in layers]
        self.assertNotIn("debug_traces", ids)
    
    def test_layer_visibility(self):
        layers = parse_layers(self.root, canvas_height=300)
        layer_dict = {l.layer_id: l for l in layers}
        
        self.assertTrue(layer_dict["layer1"].visible)
        self.assertTrue(layer_dict["layer2"].visible)
        self.assertFalse(layer_dict["layer3"].visible)  # display:none
        self.assertTrue(layer_dict["layer4"].visible)
        self.assertTrue(layer_dict["layer5"].visible)
    
    def test_layer_curves_parsed(self):
        layers = parse_layers(self.root, canvas_height=300)
        layer_dict = {l.layer_id: l for l in layers}
        
        # layer1: rect
        self.assertGreater(len(layer_dict["layer1"].curves), 0)
        # layer2: circle
        self.assertGreater(len(layer_dict["layer2"].curves), 0)
        # layer3: ellipse (hidden but parsed)
        self.assertGreater(len(layer_dict["layer3"].curves), 0)
        # layer4: line
        self.assertGreater(len(layer_dict["layer4"].curves), 0)
        # layer5: rect + sublayer circle
        self.assertGreater(len(layer_dict["layer5"].curves), 0)
        # root: rect
        self.assertGreater(len(layer_dict["__root__"].curves), 0)
    
    def test_unconverted_text_count(self):
        layers = parse_layers(self.root, canvas_height=300)
        layer_dict = {l.layer_id: l for l in layers}
        
        # layer4 has one text element
        self.assertEqual(layer_dict["layer4"].unconverted_text_count, 1)
        # Others have none
        self.assertEqual(layer_dict["layer1"].unconverted_text_count, 0)
        self.assertEqual(layer_dict["layer2"].unconverted_text_count, 0)
    
    def test_sublayer_separate(self):
        layers = parse_layers(self.root, canvas_height=300)
        layer_dict = {l.layer_id: l for l in layers}
        
        # Sublayer should be separate
        self.assertIn("layer5_sublayer", layer_dict)
        self.assertEqual(layer_dict["layer5_sublayer"].label, "Sublayer Child")
        # Parent layer has its own curves (rect)
        self.assertGreater(len(layer_dict["layer5"].curves), 0)
        # Sublayer has its own curves (circle)
        self.assertGreater(len(layer_dict["layer5_sublayer"].curves), 0)
    
    def test_invalid_order_raises(self):
        with self.assertRaises(ValueError):
            parse_layers(self.root, canvas_height=300, order="invalid")


class TestParseShapesSVG(unittest.TestCase):
    """Test parsing SVG with basic shapes using parse_root and parse_layers."""
    
    def test_parse_root_with_shapes(self):
        root = ElementTree.fromstring(TEST_SVG_SHAPES)
        curves = parse_root(root, canvas_height=200)
        # 7 shapes: rect, rounded rect, circle, ellipse, line, polyline, polygon
        # Each shape may produce multiple curves (e.g., circle = 4 cubic beziers)
        self.assertGreater(len(curves), 7)
    
    def test_parse_layers_with_shapes(self):
        root = ElementTree.fromstring(TEST_SVG_SHAPES)
        # Wrap shapes in layers for testing
        svg_with_layers = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="200mm" height="200mm" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
  <g id="shapes_layer" inkscape:groupmode="layer" inkscape:label="Shapes">
    <rect x="10" y="10" width="50" height="40" fill="none" stroke="black"/>
    <circle cx="100" cy="100" r="30" fill="none" stroke="black"/>
  </g>
</svg>
'''
        root = ElementTree.fromstring(svg_with_layers)
        layers = parse_layers(root, canvas_height=200)
        self.assertEqual(len(layers), 1)
        self.assertEqual(layers[0].label, "Shapes")
        self.assertGreater(len(layers[0].curves), 0)


class TestExistingParseRoot(unittest.TestCase):
    """Test that existing parse_root still works (backward compatibility)."""
    
    def test_parse_root_paths_only(self):
        # Original test file
        test_file = r"C:\Users\ZEUS-CORE-i7\Downloads\J-Tech-Photonics-Laser-Tool-2.5.1\laser\test_samples\test_300x300.svg"
        if os.path.exists(test_file):
            curves = parse_file(test_file)
            self.assertGreater(len(curves), 0)
        else:
            # Create a simple path-only SVG
            svg = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="100mm" height="100mm" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <path d="M 10 10 L 90 10 L 90 90 L 10 90 Z" fill="none" stroke="black"/>
</svg>
'''
            root = ElementTree.fromstring(svg)
            curves = parse_root(root, canvas_height=100)
            self.assertGreater(len(curves), 0)
    
    def test_parse_string(self):
        svg = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="100mm" height="100mm" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <path d="M 10 10 L 90 10 L 90 90 L 10 90 Z" fill="none" stroke="black"/>
</svg>
'''
        curves = parse_string(svg, canvas_height=100)
        self.assertGreater(len(curves), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)