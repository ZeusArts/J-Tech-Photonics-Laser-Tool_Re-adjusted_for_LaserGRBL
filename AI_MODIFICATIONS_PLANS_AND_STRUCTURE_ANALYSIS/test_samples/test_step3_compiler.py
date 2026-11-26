#!/usr/bin/env python3
"""
Unit tests for Step 3: Multi-layer compiler.
Tests svg_to_gcode.compiler.MultiLayerCompiler with LayerJob.
"""

import unittest
import tempfile
import os
from xml.etree import ElementTree

from svg_to_gcode.compiler import LayerJob, MultiLayerCompiler, sanitize_filename
from svg_to_gcode.svg_parser import parse_root, parse_layers
from svg_to_gcode.geometry import Line, Vector, CubicBazier


# Simple test SVG with layers for integration testing
TEST_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="100mm" height="100mm" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
  <g id="engrave" inkscape:groupmode="layer" inkscape:label="Engrave Layer">
    <rect x="10" y="10" width="20" height="20" fill="none" stroke="black"/>
  </g>
  <g id="cut" inkscape:groupmode="layer" inkscape:label="Cut Layer">
    <rect x="50" y="50" width="30" height="30" fill="none" stroke="black"/>
  </g>
</svg>
'''


class TestSanitizeFilename(unittest.TestCase):
    """Test filename sanitization for Windows."""
    
    def test_normal_name(self):
        self.assertEqual(sanitize_filename("Normal Layer"), "Normal_Layer")
    
    def test_windows_forbidden_chars(self):
        self.assertEqual(sanitize_filename('Cut/Engrave:Test*1'), 'Cut_Engrave_Test_1')
        self.assertEqual(sanitize_filename('Path\\With|Chars'), 'Path_With_Chars')
        self.assertEqual(sanitize_filename('Quote"Test'), 'Quote_Test')
        self.assertEqual(sanitize_filename('Less<Greater'), 'Less_Greater')
    
    def test_control_chars(self):
        self.assertEqual(sanitize_filename("Line1\nLine2"), "Line1_Line2")
        self.assertEqual(sanitize_filename("Tab\there"), "Tab_here")
    
    def test_leading_trailing_strip(self):
        self.assertEqual(sanitize_filename("  Layer  "), "Layer")
        self.assertEqual(sanitize_filename(".Layer."), "Layer")
        self.assertEqual(sanitize_filename(" .Layer. "), "Layer")
    
    def test_multiple_underscores_collapsed(self):
        self.assertEqual(sanitize_filename("A___B"), "A_B")
    
    def test_empty_returns_default(self):
        self.assertEqual(sanitize_filename(""), "layer")
        self.assertEqual(sanitize_filename("***"), "_")
        self.assertEqual(sanitize_filename("   "), "layer")


class TestLayerJob(unittest.TestCase):
    """Test LayerJob dataclass."""
    
    def test_defaults(self):
        job = LayerJob(layer_id="test", label="Test", curves=[])
        self.assertEqual(job.enabled, True)
        self.assertEqual(job.laser_mode, "M3")
        self.assertEqual(job.laser_power, 255)
        self.assertEqual(job.laser_off_command, "M5;")
        self.assertIsNone(job.laser_power_command)
        self.assertEqual(job.travel_speed, 3000.0)
        self.assertEqual(job.cutting_speed, 750.0)
        self.assertEqual(job.passes, 1)
        self.assertEqual(job.pass_depth, 0.0)
        self.assertEqual(job.dwell_time, 0.0)
    
    def test_custom_values(self):
        job = LayerJob(
            layer_id="test", label="Test", curves=[],
            laser_mode="M4", laser_power=1000,
            laser_power_command="M3 S{power};\\nG4 P10;",
            passes=3, pass_depth=0.5
        )
        self.assertEqual(job.laser_mode, "M4")
        self.assertEqual(job.laser_power, 1000)
        self.assertEqual(job.laser_power_command, "M3 S{power};\\nG4 P10;")
        self.assertEqual(job.passes, 3)
        self.assertEqual(job.pass_depth, 0.5)


class TestMultiLayerCompilerCombined(unittest.TestCase):
    """Test combined (single file) output mode."""
    
    def setUp(self):
        self.compiler = MultiLayerCompiler(unit="mm")
        
        # Create simple line curves for testing
        self.engrave_curves = [
            Line(Vector(10, 90), Vector(30, 90)),
            Line(Vector(30, 90), Vector(30, 70)),
            Line(Vector(30, 70), Vector(10, 70)),
            Line(Vector(10, 70), Vector(10, 90)),
        ]
        
        self.cut_curves = [
            Line(Vector(50, 50), Vector(80, 50)),
            Line(Vector(80, 50), Vector(80, 20)),
            Line(Vector(80, 20), Vector(50, 20)),
            Line(Vector(50, 20), Vector(50, 50)),
        ]
    
    def test_combined_basic(self):
        """Test basic combined compilation with two jobs."""
        jobs = [
            LayerJob(
                layer_id="engrave", label="Engrave", curves=self.engrave_curves,
                laser_mode="M4", laser_power=400, cutting_speed=2000, travel_speed=3000,
                passes=1, pass_depth=0
            ),
            LayerJob(
                layer_id="cut", label="Cut", curves=self.cut_curves,
                laser_mode="M3", laser_power=900, cutting_speed=300, travel_speed=3000,
                passes=2, pass_depth=0
            ),
        ]
        
        gcode = self.compiler.compile_combined(jobs)
        
        # Check header
        self.assertIn("G90;", gcode)
        self.assertIn("G21;", gcode)  # mm
        
        # Check both jobs present
        self.assertIn("; === Layer 1: Engrave ===", gcode)
        self.assertIn("; === Layer 2: Cut ===", gcode)
        
        # Check engrave job commands
        self.assertIn("M4 S400;", gcode)  # Engrave laser on
        self.assertIn("F2000", gcode)     # Engrave cutting speed
        self.assertIn("F3000", gcode)     # Travel speed
        
        # Check cut job commands
        self.assertIn("M3 S900;", gcode)  # Cut laser on
        self.assertIn("F300", gcode)      # Cut cutting speed
        
        # Check laser off between jobs
        self.assertIn("M5;", gcode)
        
        # Check no Z commands (pass_depth=0)
        self.assertNotIn("G91", gcode)
        self.assertNotIn("Z", gcode)
    
    def test_combined_same_start_point_outputs_commands(self):
        """Test that job switch re-outputs travel/laser commands even at same position."""
        # Two jobs with curves starting at same point
        curves1 = [Line(Vector(10, 10), Vector(20, 10))]
        curves2 = [Line(Vector(10, 10), Vector(20, 10))]  # Same start
        
        jobs = [
            LayerJob(layer_id="1", label="Job1", curves=curves1, laser_mode="M3", laser_power=500, cutting_speed=1000),
            LayerJob(layer_id="2", label="Job2", curves=curves2, laser_mode="M3", laser_power=800, cutting_speed=500),
        ]
        
        gcode = self.compiler.compile_combined(jobs)
        
        # Should have both laser power commands
        self.assertIn("M3 S500;", gcode)
        self.assertIn("M3 S800;", gcode)
        
        # Should have both cutting speeds
        self.assertIn("F1000", gcode)
        self.assertIn("F500", gcode)
    
    def test_combined_escape_expansion(self):
        """Test that \\n in custom commands is expanded."""
        jobs = [
            LayerJob(
                layer_id="test", label="Test", curves=self.engrave_curves,
                laser_power_command="M3 S255;\\nG4 P0.5;",  # Multi-line command
                laser_off_command="M5;\\nG4 P0.1;"
            ),
        ]
        
        gcode = self.compiler.compile_combined(jobs)
        
        # Check that \n became actual newlines
        self.assertIn("M3 S255;", gcode)
        self.assertIn("G4 P0.5;", gcode)
        self.assertIn("M5;", gcode)
        self.assertIn("G4 P0.1;", gcode)
        
        # Should be on separate lines
        lines = gcode.split('\n')
        self.assertTrue(any("M3 S255;" in l for l in lines))
        self.assertTrue(any("G4 P0.5;" in l for l in lines))
    
    def test_combined_custom_header_footer(self):
        """Test custom header/footer are included."""
        compiler = MultiLayerCompiler(
            unit="mm",
            custom_header=["G28;", "M3 S0;"],
            custom_footer=["M5;", "G28;"]
        )
        
        jobs = [
            LayerJob(layer_id="test", label="Test", curves=self.engrave_curves),
        ]
        
        gcode = compiler.compile_combined(jobs)
        
        self.assertIn("G28;", gcode)
        self.assertIn("M3 S0;", gcode)
        # Footer should appear at end
        self.assertTrue(gcode.strip().endswith("G28;"))
    
    def test_combined_skips_disabled_jobs(self):
        """Test that disabled jobs are skipped."""
        jobs = [
            LayerJob(layer_id="1", label="Enabled", curves=self.engrave_curves, enabled=True),
            LayerJob(layer_id="2", label="Disabled", curves=self.cut_curves, enabled=False),
        ]
        
        gcode = self.compiler.compile_combined(jobs)
        
        self.assertIn("; === Layer 1: Enabled ===", gcode)
        self.assertNotIn("Disabled", gcode)
    
    def test_combined_skips_empty_curves(self):
        """Test that jobs with empty curves are skipped."""
        jobs = [
            LayerJob(layer_id="1", label="Has Curves", curves=self.engrave_curves),
            LayerJob(layer_id="2", label="No Curves", curves=[]),
        ]
        
        gcode = self.compiler.compile_combined(jobs)
        
        self.assertIn("Has Curves", gcode)
        self.assertNotIn("No Curves", gcode)
    
    def test_combined_warns_no_active_jobs(self):
        """Test warning when no active jobs."""
        jobs = [
            LayerJob(layer_id="1", label="Disabled", curves=[], enabled=False),
            LayerJob(layer_id="2", label="Empty", curves=[]),
        ]
        
        with self.assertWarns(UserWarning):
            gcode = self.compiler.compile_combined(jobs)
        
        self.assertEqual(gcode.strip(), "")
    
    def test_combined_pass_depth_zero_no_z(self):
        """Test that pass_depth=0 produces no Z commands even with passes>1."""
        jobs = [
            LayerJob(
                layer_id="test", label="Test", curves=self.engrave_curves,
                passes=3, pass_depth=0.0
            ),
        ]
        
        gcode = self.compiler.compile_combined(jobs)
        
        self.assertNotIn("G91", gcode)
        self.assertNotIn("Z", gcode)
        # Pass 0: M5 at start (from body), M5 at end
        # Pass 1: M5 at end
        # Pass 2: M5 at end (final)
        # Total: 4
        m5_count = gcode.count("M5;")
        self.assertEqual(m5_count, 4)  # Pass 0 start + after each of 3 passes
    
    def test_combined_passes_with_depth(self):
        """Test that pass_depth>0 produces Z commands between passes."""
        jobs = [
            LayerJob(
                layer_id="test", label="Test", curves=self.engrave_curves,
                passes=2, pass_depth=1.0
            ),
        ]
        
        gcode = self.compiler.compile_combined(jobs)
        
        # Should have Z move
        self.assertIn("G91", gcode)
        self.assertIn("Z-1.0", gcode)
        self.assertIn("G90", gcode)
    
    def test_combined_inches_unit(self):
        """Test G20 for inches unit."""
        compiler = MultiLayerCompiler(unit="in")
        jobs = [LayerJob(layer_id="test", label="Test", curves=self.engrave_curves)]
        
        gcode = compiler.compile_combined(jobs)
        
        self.assertIn("G20;", gcode)
        self.assertNotIn("G21;", gcode)


class TestMultiLayerCompilerSeparate(unittest.TestCase):
    """Test separate (per-layer files) output mode."""
    
    def setUp(self):
        self.compiler = MultiLayerCompiler(unit="mm")
        
        self.engrave_curves = [
            Line(Vector(10, 90), Vector(30, 90)),
            Line(Vector(30, 90), Vector(30, 70)),
            Line(Vector(30, 70), Vector(10, 70)),
            Line(Vector(10, 70), Vector(10, 90)),
        ]
        
        self.cut_curves = [
            Line(Vector(50, 50), Vector(80, 50)),
            Line(Vector(80, 50), Vector(80, 20)),
            Line(Vector(80, 20), Vector(50, 20)),
            Line(Vector(50, 20), Vector(50, 50)),
        ]
    
    def test_separate_basic(self):
        """Test separate file generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs = [
                LayerJob(layer_id="engrave", label="Engrave", curves=self.engrave_curves),
                LayerJob(layer_id="cut", label="Cut", curves=self.cut_curves),
            ]
            
            files = self.compiler.compile_separate(jobs, tmpdir, "output.gcode")
            
            self.assertEqual(len(files), 2)
            
            # Check file names
            self.assertTrue(any("01_Engrave.gcode" in f for f in files))
            self.assertTrue(any("02_Cut.gcode" in f for f in files))
            
            # Check each file is complete (has header and footer)
            for f in files:
                with open(f, 'r') as fh:
                    content = fh.read()
                self.assertIn("G90;", content)
                self.assertIn("G21;", content)
                self.assertIn("M5;", content)  # Laser off at end
    
    def test_separate_windows_forbidden_chars_in_label(self):
        """Test that Windows forbidden chars in label are sanitized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs = [
                LayerJob(layer_id="test", label='Cut/Engrave:Test*1', curves=self.engrave_curves),
            ]
            
            files = self.compiler.compile_separate(jobs, tmpdir, "output.gcode")
            
            self.assertEqual(len(files), 1)
            filename = os.path.basename(files[0])
            # Forbidden chars should be replaced
            self.assertNotIn("/", filename)
            self.assertNotIn(":", filename)
            self.assertNotIn("*", filename)
            self.assertIn("Cut_Engrave_Test_1", filename)
    
    def test_separate_add_numeric_suffix(self):
        """Test numeric suffix for collision avoidance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs = [
                LayerJob(layer_id="1", label="Same", curves=self.engrave_curves),
                LayerJob(layer_id="2", label="Same", curves=self.cut_curves),
            ]
            
            # First call creates files
            files1 = self.compiler.compile_separate(jobs, tmpdir, "output.gcode", add_numeric_suffix=True)
            
            # Second call should add suffix
            files2 = self.compiler.compile_separate(jobs, tmpdir, "output.gcode", add_numeric_suffix=True)
            
            # Should have 4 files total
            all_files = set(files1 + files2)
            self.assertEqual(len(all_files), 4)
            
            # Second set should have _1 suffix
            for f in files2:
                self.assertIn("_1.gcode", f)
    
    def test_separate_skips_disabled_and_empty(self):
        """Test that disabled/empty jobs don't create files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs = [
                LayerJob(layer_id="1", label="Enabled", curves=self.engrave_curves, enabled=True),
                LayerJob(layer_id="2", label="Disabled", curves=self.cut_curves, enabled=False),
                LayerJob(layer_id="3", label="Empty", curves=[], enabled=True),
            ]
            
            files = self.compiler.compile_separate(jobs, tmpdir, "output.gcode")
            
            self.assertEqual(len(files), 1)
            self.assertIn("Enabled", files[0])
    
    def test_separate_independent_files(self):
        """Test that each file is independently valid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs = [
                LayerJob(
                    layer_id="engrave", label="Engrave", curves=self.engrave_curves,
                    laser_mode="M4", laser_power=400, cutting_speed=2000
                ),
                LayerJob(
                    layer_id="cut", label="Cut", curves=self.cut_curves,
                    laser_mode="M3", laser_power=900, cutting_speed=300
                ),
            ]
            
            files = self.compiler.compile_separate(jobs, tmpdir, "output.gcode")
            
            # Files are ordered by job order (engrave first, cut second)
            # Find which file is which by content
            engrave_content = None
            cut_content = None
            for f in files:
                with open(f, 'r') as fh:
                    c = fh.read()
                if "M4 S400;" in c:
                    engrave_content = c
                elif "M3 S900;" in c:
                    cut_content = c
            
            self.assertIsNotNone(engrave_content, "Engrave file not found")
            self.assertIsNotNone(cut_content, "Cut file not found")
            
            # Check engrave file has engrave settings
            self.assertIn("M4 S400;", engrave_content)
            self.assertIn("F2000", engrave_content)
            self.assertNotIn("M3 S900;", engrave_content)
            # F3000 (travel speed) contains F300 as substring, so check for exact cutting speed
            self.assertNotIn("F300 ", engrave_content.replace("F300;", "F300 "))  # No F300 cutting speed
            
            # Check cut file has cut settings
            self.assertIn("M3 S900;", cut_content)
            self.assertIn("F300", cut_content)
            self.assertNotIn("M4 S400;", cut_content)
            self.assertNotIn("F2000", cut_content)
            
            # Both should have complete headers/footers
            for content in [engrave_content, cut_content]:
                self.assertIn("G90;", content)
                self.assertIn("G21;", content)
                self.assertIn("M5;", content)


class TestIntegrationWithParser(unittest.TestCase):
    """Integration test with svg_parser."""
    
    def test_parse_layers_then_compile(self):
        """Test full pipeline: parse_layers -> LayerJob -> compile."""
        root = ElementTree.fromstring(TEST_SVG)
        # Use bottom_to_top to get DOM order: Engrave first, then Cut
        layers = parse_layers(root, canvas_height=100, order="bottom_to_top")
        
        # Convert to LayerJobs
        jobs = []
        for i, layer in enumerate(layers):
            if layer.layer_id == "__root__":
                continue
            job = LayerJob(
                layer_id=layer.layer_id,
                label=layer.label,
                curves=layer.curves,
                enabled=layer.visible,
                laser_mode="M4" if "Engrave" in layer.label else "M3",
                laser_power=400 if "Engrave" in layer.label else 900,
                cutting_speed=2000 if "Engrave" in layer.label else 300,
            )
            jobs.append(job)
        
        compiler = MultiLayerCompiler(unit="mm")
        gcode = compiler.compile_combined(jobs)
        
        self.assertIn("; === Layer 1: Engrave Layer ===", gcode)
        self.assertIn("; === Layer 2: Cut Layer ===", gcode)
        self.assertIn("M4 S400;", gcode)
        self.assertIn("M3 S900;", gcode)
        self.assertIn("F2000", gcode)
        self.assertIn("F300", gcode)


if __name__ == "__main__":
    unittest.main(verbosity=2)