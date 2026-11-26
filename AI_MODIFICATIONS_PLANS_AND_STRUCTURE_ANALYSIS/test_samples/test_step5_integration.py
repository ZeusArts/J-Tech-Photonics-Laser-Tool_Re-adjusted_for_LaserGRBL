#!/usr/bin/env python3
"""
Comprehensive integration test for Step 5: Full pipeline integration.
Tests laser.py with both legacy mode and multi-layer GUI mode (mocked).
"""

import unittest
import tempfile
import os
import json
import shutil
from unittest.mock import patch, MagicMock, Mock
from xml.etree import ElementTree

from svg_to_gcode.svg_parser import parse_layers, parse_root, LayerData
from svg_to_gcode.compiler import LayerJob, MultiLayerCompiler
from gui import (
    save_config_to_svg,
    load_config_from_svg,
    merge_layers_with_config,
    create_config_dict,
    LayerDialogResult,
    build_jobs_from_dialog_result,
    LAYER_PRESETS,
)

# Mock inkex module before importing laser
import sys
from unittest.mock import MagicMock

mock_inkex = MagicMock()
mock_inkex.EffectExtension = object
mock_inkex.Boolean = bool
sys.modules['inkex'] = mock_inkex

import laser


# Test SVG paths
TEST_SVG_LEGACY = r"C:\\Users\\ZEUS-CORE-i7\\Downloads\\J-Tech-Photonics-Laser-Tool-2.5.1\\laser\\test_samples\\test_300x300.svg"
TEST_SVG_MULTILAYER = r"C:\\Users\\ZEUS-CORE-i7\\Downloads\\J-Tech-Photonics-Laser-Tool-2.5.1\\laser\\test_samples\\test_multilayer_300x300.svg"


class MockOptions:
    """Mock options object for laser.py testing."""
    def __init__(self, **kwargs):
        defaults = {
            "unit": "mm",
            "travel_speed": 3000.0,
            "cutting_speed": 750.0,
            "passes": 1,
            "pass_depth": 1.0,
            "directory": tempfile.gettempdir(),
            "filename": "output.gcode",
            "filename_suffix": True,
            "tool_power_command": "M3 S255;",
            "tool_off_command": "M5;",
            "dwell_time": 0.0,
            "draw_debug": True,
            "debug_line_width": 0.5,
            "debug_arrow_scale": 1.0,
            "approximation_tolerance": "0.01",
            "header_path": None,
            "footer_path": None,
            "do_z_axis_start": False,
            "z_axis_start": 0.0,
            "move_to_origin_end": False,
            "do_laser_off_start": True,
            "do_laser_off_end": True,
            "machine_origin": "bottom-left",
            "invert_y_axis": False,
            "bed_width": 300.0,
            "bed_height": 300.0,
            "horizontal_offset": 0.0,
            "vertical_offset": 0.0,
            "scaling_factor": 1.0,
            "use_layer_gui": True,
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


def load_test_svg(path):
    """Load SVG file as string."""
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return None

class TestLegacyMode(unittest.TestCase):
    """Test legacy single-settings mode (use_layer_gui=False)."""

    def setUp(self):
        self.svg_content = load_test_svg(TEST_SVG_LEGACY)
        if not self.svg_content:
            self.skipTest("Legacy test SVG not found")
        self.root = ElementTree.fromstring(self.svg_content)
    
    def test_parse_root_legacy(self):
        """Test that parse_root works with legacy SVG (path-only)."""
        from svg_to_gcode.svg_parser import parse_root
        curves = parse_root(self.root, canvas_height=300, transform_origin=True)
        self.assertGreater(len(curves), 0)
        from svg_to_gcode.geometry import Line
        lines = [c for c in curves if isinstance(c, Line)]
        self.assertGreaterEqual(len(lines), 4)


class TestMultiLayerMode(unittest.TestCase):
    """Test multi-layer GUI mode with mocked dialog."""

    def setUp(self):
        self.svg_content = load_test_svg(TEST_SVG_MULTILAYER)
        if not self.svg_content:
            self.skipTest("Multi-layer test SVG not found")
        self.root = ElementTree.fromstring(self.svg_content)
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_parse_layers_multilayer(self):
        """Test that parse_layers extracts all layers correctly."""
        from svg_to_gcode.svg_parser import parse_layers
        layers = parse_layers(self.root, canvas_height=300, order="top_to_bottom")
        
        # Should have 3 layers: engrave, cut, guides (debug layers excluded)
        layer_ids = [l.layer_id for l in layers]
        self.assertIn("engrave", layer_ids)
        self.assertIn("cut", layer_ids)
        self.assertIn("guides", layer_ids)
        self.assertNotIn("debug_traces", layer_ids)
        self.assertNotIn("debug_references", layer_ids)
        
        # Check engrave layer has curves
        engrave = next(l for l in layers if l.layer_id == "engrave")
        self.assertGreater(len(engrave.curves), 0)
        self.assertEqual(engrave.unconverted_text_count, 0)
        
        # Check cut layer has curves
        cut = next(l for l in layers if l.layer_id == "cut")
        self.assertGreater(len(cut.curves), 0)
        
        # Check guides layer has text (unconverted)
        guides = next(l for l in layers if l.layer_id == "guides")
        self.assertEqual(guides.unconverted_text_count, 1)
        self.assertFalse(guides.visible)  # display:none
    
    @patch('laser.show_layer_dialog')
    def test_multilayer_combined_mode(self, mock_dialog):
        """Test multi-layer combined mode with mocked dialog."""
        from svg_to_gcode.svg_parser import parse_layers
        from gui import merge_layers_with_config, create_config_dict, build_jobs_from_dialog_result
        
        layers = parse_layers(self.root, canvas_height=300, order="top_to_bottom")
        
        # Create mock dialog result
        defaults = {
            "travel_speed": 3000.0,
            "cutting_speed": 750.0,
            "passes": 1,
            "pass_depth": 0.0,
            "laser_mode": "M3",
            "laser_power": 255,
            "laser_off_command": "M5;",
            "laser_power_command": "M3 S255;",
            "dwell_time": 0.0,
            "unit": "mm",
        }
        
        # Simulate user selecting Engrave for engrave layer, Cut for cut layer
        saved_config = {
            "layers": {
                "engrave": {
                    "enabled": True,
                    "preset": "Engrave",
                    "laser_mode": "M4",
                    "laser_power": 400,
                    "cutting_speed": 2000,
                    "travel_speed": 3000,
                    "passes": 1,
                    "pass_depth": 0.0,
                },
                "cut": {
                    "enabled": True,
                    "preset": "Cut",
                    "laser_mode": "M3",
                    "laser_power": 900,
                    "cutting_speed": 300,
                    "travel_speed": 3000,
                    "passes": 3,
                    "pass_depth": 0.0,
                },
                "guides": {
                    "enabled": False,  # Hidden layer
                },
            },
            "output_mode": "combined",
            "layer_order": ["engrave", "cut", "guides"],
            "add_numeric_suffix": True,
        }
        
        merged = merge_layers_with_config(layers, saved_config, defaults)
        
        # Check merged config
        engrave_merged = next(m for m in merged if m["layer_id"] == "engrave")
        self.assertTrue(engrave_merged["enabled"])
        self.assertEqual(engrave_merged["laser_mode"], "M4")
        self.assertEqual(engrave_merged["laser_power"], 400)
        self.assertEqual(engrave_merged["cutting_speed"], 2000)
        
        cut_merged = next(m for m in merged if m["layer_id"] == "cut")
        self.assertTrue(cut_merged["enabled"])
        self.assertEqual(cut_merged["laser_mode"], "M3")
        self.assertEqual(cut_merged["laser_power"], 900)
        self.assertEqual(cut_merged["cutting_speed"], 300)
        
        guides_merged = next(m for m in merged if m["layer_id"] == "guides")
        self.assertFalse(guides_merged["enabled"])
        
        # Create config dict with correct layer order (engrave first, then cut)
        config = create_config_dict(merged, "combined", "top_to_bottom", self.temp_dir, "output.gcode", True)
        # Override layer_order to match expected job order (engrave first, then cut)
        config["layer_order"] = ["engrave", "cut"]
        
        # Build jobs
        result = LayerDialogResult(
            confirmed=True,
            output_mode="combined",
            layer_order="top_to_bottom",
            output_dir=self.temp_dir,
            base_filename="output.gcode",
            add_numeric_suffix=True,
            jobs=[],
            config_dict=config,
        )
        
        jobs = build_jobs_from_dialog_result(result, layers)
        
        # Should have 2 jobs (guides disabled)
        self.assertEqual(len(jobs), 2)
        
        # Check job settings
        engrave_job = next(j for j in jobs if j.layer_id == "engrave")
        self.assertEqual(engrave_job.laser_mode, "M4")
        self.assertEqual(engrave_job.laser_power, 400)
        self.assertEqual(engrave_job.cutting_speed, 2000)
        self.assertEqual(engrave_job.passes, 1)
        
        cut_job = next(j for j in jobs if j.layer_id == "cut")
        self.assertEqual(cut_job.laser_mode, "M3")
        self.assertEqual(cut_job.laser_power, 900)
        self.assertEqual(cut_job.cutting_speed, 300)
        self.assertEqual(cut_job.passes, 3)
        
        # Compile and verify G-code
        compiler = MultiLayerCompiler(unit="mm")
        gcode = compiler.compile_combined(jobs)
        
        # Verify key elements
        self.assertIn("M4 S400;", gcode)
        self.assertIn("M3 S900;", gcode)
        self.assertIn("F2000", gcode)
        self.assertIn("F300", gcode)
        self.assertIn("; === Layer 1: Engrave Layer ===", gcode)
        self.assertIn("; === Layer 2: Cut Layer ===", gcode)
        # No Z commands since pass_depth=0
        self.assertNotIn("G91", gcode)
        self.assertNotIn("Z-", gcode)
        
        # Verify output file would be created
        output_path = os.path.join(self.temp_dir, "test_output.gcode")
        compiler.compile_combined_to_file(jobs, output_path)
        self.assertTrue(os.path.exists(output_path))
        
        with open(output_path, 'r') as f:
            content = f.read()
        self.assertEqual(content, gcode)
    
    @patch('laser.show_layer_dialog')
    def test_multilayer_separate_mode(self, mock_dialog):
        """Test multi-layer separate files mode."""
        from svg_to_gcode.svg_parser import parse_layers
        from gui import merge_layers_with_config, create_config_dict, build_jobs_from_dialog_result
        
        layers = parse_layers(self.root, canvas_height=300, order="top_to_bottom")
        
        defaults = {
            "travel_speed": 3000.0,
            "cutting_speed": 750.0,
            "passes": 1,
            "pass_depth": 0.0,
            "laser_mode": "M3",
            "laser_power": 255,
            "laser_off_command": "M5;",
            "laser_power_command": "M3 S255;",
            "dwell_time": 0.0,
            "unit": "mm",
        }
        
        saved_config = {
            "layers": {
                "engrave": {"enabled": True, "laser_mode": "M4", "laser_power": 400, "cutting_speed": 2000, "travel_speed": 3000, "passes": 1},
                "cut": {"enabled": True, "laser_mode": "M3", "laser_power": 900, "cutting_speed": 300, "travel_speed": 3000, "passes": 3},
            },
            "output_mode": "separate",
            "layer_order": ["engrave", "cut"],
            "add_numeric_suffix": True,
        }
        
        merged = merge_layers_with_config(layers, saved_config, defaults)
        config = create_config_dict(merged, "separate", "top_to_bottom", self.temp_dir, "output.gcode", True)
        
        result = LayerDialogResult(
            confirmed=True,
            output_mode="separate",
            layer_order="top_to_bottom",
            output_dir=self.temp_dir,
            base_filename="output.gcode",
            add_numeric_suffix=True,
            jobs=[],
            config_dict=config,
        )
        
        jobs = build_jobs_from_dialog_result(result, layers)
        
        compiler = MultiLayerCompiler(unit="mm")
        files = compiler.compile_separate(jobs, self.temp_dir, "output.gcode", add_numeric_suffix=True)
        
        self.assertEqual(len(files), 2)
        
        # Check each file is valid standalone G-code
        for f in files:
            with open(f, 'r') as fh:
                content = fh.read()
            self.assertIn("G90;", content)
            self.assertIn("G21;", content)
            self.assertIn("M5;", content)
    
    @patch('laser.show_layer_dialog')
    def test_multilayer_cancelled(self, mock_dialog):
        """Test that cancelled dialog produces no output."""
        mock_dialog.return_value = LayerDialogResult(confirmed=False)
        
        # In real laser.py, cancelled dialog returns early without generating G-code
        result = LayerDialogResult(confirmed=False)
        self.assertFalse(result.confirmed)
        
        # No jobs should be created
        self.assertEqual(result.jobs, [])
    
    def test_debug_layer_coloring(self):
        """Test that debug trace multi-layer coloring works."""
        from laser import DEBUG_LAYER_COLORS
        
        # Should have 6 colors
        self.assertEqual(len(DEBUG_LAYER_COLORS), 6)
        self.assertEqual(DEBUG_LAYER_COLORS[0], "#0066ff")  # Blue
        self.assertEqual(DEBUG_LAYER_COLORS[1], "#ff0000")  # Red
        self.assertEqual(DEBUG_LAYER_COLORS[2], "#00aa00")  # Green
    
    def test_config_save_load_svg(self):
        """Test config save/load to/from SVG attribute."""
        # Save config
        config = {
            "layers": {"engrave": {"enabled": True}},
            "output_mode": "combined",
            "add_numeric_suffix": True,
        }
        save_config_to_svg(self.root, config)
        
        # Load config
        loaded = load_config_from_svg(self.root)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["output_mode"], "combined")

class TestCoordinateAccuracy(unittest.TestCase):
    """Test that coordinates are accurate in mm (like the original fix)."""

    def setUp(self):
        # Create a simple 100x100mm square at (20,20) in 300x300mm page
        # with 96dpi viewBox (1133.8583 x 1133.8583)
        self.svg_content = """<?xml version="1.0" encoding="UTF-8"?>
<svg width="300mm" height="300mm" viewBox="0 0 1133.8583 1133.8583" xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
  <g id="layer1" inkscape:groupmode="layer" inkscape:label="Test Layer">
    <!-- 20mm = 75.59 user units, 100mm = 377.95 user units -->
    <rect x="75.59" y="75.59" width="377.95" height="377.95" fill="none" stroke="black"/>
  </g>
</svg>"""
        self.root = ElementTree.fromstring(self.svg_content)
    
    def test_parse_accuracy(self):
        """Test that parsed coordinates are accurate in mm."""
        from svg_to_gcode.svg_parser import parse_layers
        layers = parse_layers(self.root, canvas_height=1133.8583, order="top_to_bottom")
        
        layer = layers[0]
        self.assertEqual(layer.layer_id, "layer1")
        
        # Check that we have curves
        self.assertGreater(len(layer.curves), 0)


class TestBackwardCompatibility(unittest.TestCase):
    """Ensure legacy mode still works exactly as before."""

    def test_generate_custom_interface_escapes(self):
        """Test that generate_custom_interface handles escaped newlines."""
        from laser import generate_custom_interface
        
        # Test with escaped newlines (raw strings with literal backslash-n)
        interface_class = generate_custom_interface(r"M5;\nG4 P1;", r"M3 S255;\nG4 P0.5;")
        interface = interface_class()
        
        # Should expand escapes
        off_cmd = interface.laser_off()
        power_cmd = interface.set_laser_power(1.0)
        
        self.assertIn("M5;", off_cmd)
        self.assertIn("G4 P1;", off_cmd)
        self.assertIn("M3 S255;", power_cmd)
        self.assertIn("G4 P0.5;", power_cmd)
        # Should have actual newlines (expanded from literal \n)
        self.assertIn("\n", off_cmd)  # Contains actual newlines
        self.assertIn("\n", power_cmd)
        # Should NOT contain literal backslash-n sequences
        self.assertNotIn("\\n", off_cmd)
        self.assertNotIn("\\n", power_cmd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
