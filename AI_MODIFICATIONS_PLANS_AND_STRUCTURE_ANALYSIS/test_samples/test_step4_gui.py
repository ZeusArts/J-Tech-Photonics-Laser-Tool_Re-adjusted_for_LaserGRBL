#!/usr/bin/env python3
"""
Unit tests for Step 4: Multi-layer GUI configuration dialog and persistence.
Tests svg_to_gcode.gui layer_dialog functions and dialog logic.
"""

import unittest
import tempfile
import os
import json
from xml.etree import ElementTree

from svg_to_gcode.svg_parser import parse_layers, LayerData
from svg_to_gcode.compiler import LayerJob
from gui import (
    save_config_to_svg,
    load_config_from_svg,
    merge_layers_with_config,
    create_config_dict,
    save_config_to_json,
    load_config_from_json,
    LAYER_PRESETS,
    LayerDialogResult,
    build_jobs_from_dialog_result,
)


# Test SVG with multiple layers
TEST_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="300mm" height="300mm" viewBox="0 0 300 300" xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
  <g id="layer1" inkscape:groupmode="layer" inkscape:label="Engrave Layer">
    <rect x="10" y="10" width="20" height="20" fill="none" stroke="black"/>
  </g>
  <g id="layer2" inkscape:groupmode="layer" inkscape:label="Cut Layer">
    <rect x="50" y="50" width="30" height="30" fill="none" stroke="black"/>
  </g>
  <g id="layer3" inkscape:groupmode="layer" inkscape:label="Hidden Layer" style="display:none">
    <circle cx="100" cy="100" r="10" fill="none" stroke="black"/>
  </g>
  <g id="layer4" inkscape:groupmode="layer" inkscape:label="Empty Layer">
  </g>
</svg>
'''

# Test SVG with Japanese layer names
TEST_SVG_JP = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="300mm" height="300mm" viewBox="0 0 300 300" xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
  <g id="layer1" inkscape:groupmode="layer" inkscape:label="彫刻レイヤー">
    <rect x="10" y="10" width="20" height="20" fill="none" stroke="black"/>
  </g>
  <g id="layer2" inkscape:groupmode="layer" inkscape:label="カットレイヤー">
    <rect x="50" y="50" width="30" height="30" fill="none" stroke="black"/>
  </g>
</svg>
'''


class TestConfigPersistence(unittest.TestCase):
    """Test SVG/JSON configuration save/load."""

    def test_save_load_svg_config(self):
        """Test saving and loading config to/from SVG root."""
        root = ElementTree.fromstring(TEST_SVG)

        config = {
            "layers": {
                "layer1": {"enabled": True, "laser_mode": "M4", "laser_power": 400},
                "layer2": {"enabled": True, "laser_mode": "M3", "laser_power": 900},
            },
            "layer_order": ["layer1", "layer2"],
            "output_mode": "combined",
            "add_numeric_suffix": True,
        }

        save_config_to_svg(root, config)
        loaded = load_config_from_svg(root)

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["output_mode"], "combined")
        self.assertEqual(loaded["layers"]["layer1"]["laser_mode"], "M4")
        self.assertEqual(loaded["layers"]["layer2"]["laser_power"], 900)

    def test_load_missing_config(self):
        """Test loading config from SVG without config attribute."""
        root = ElementTree.fromstring(TEST_SVG)
        loaded = load_config_from_svg(root)
        self.assertIsNone(loaded)

    def test_load_invalid_json(self):
        """Test loading invalid JSON from SVG."""
        root = ElementTree.fromstring(TEST_SVG)
        root.set("data-laser-config", "not valid json")
        loaded = load_config_from_svg(root)
        self.assertIsNone(loaded)

    def test_save_load_json_file(self):
        """Test saving and loading config to/from JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            config = {
                "layers": {"layer1": {"enabled": True}},
                "output_mode": "separate",
            }
            save_config_to_json(temp_path, config)
            loaded = load_config_from_json(temp_path)

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["output_mode"], "separate")
        finally:
            os.unlink(temp_path)

    def test_load_nonexistent_json(self):
        """Test loading from non-existent JSON file."""
        loaded = load_config_from_json("/nonexistent/path.json")
        self.assertIsNone(loaded)


class TestMergeLayersWithConfig(unittest.TestCase):
    """Test merge_layers_with_config function."""

    def setUp(self):
        self.root = ElementTree.fromstring(TEST_SVG)
        self.layers = parse_layers(self.root, canvas_height=300)
        self.defaults = {
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

    def test_no_saved_config_uses_defaults(self):
        """Test that missing saved config uses defaults for all layers."""
        merged = merge_layers_with_config(self.layers, None, self.defaults)

        self.assertEqual(len(merged), 4)  # 4 layers in test SVG
        for layer in merged:
            self.assertEqual(layer["laser_mode"], "M3")
            self.assertEqual(layer["laser_power"], 255)
            self.assertEqual(layer["cutting_speed"], 750)

    def test_hidden_layer_defaults_disabled(self):
        """Test that hidden layers default to enabled=False."""
        merged = merge_layers_with_config(self.layers, None, self.defaults)

        hidden_layer = next(l for l in merged if l["layer_id"] == "layer3")
        self.assertFalse(hidden_layer["enabled"])

    def test_empty_layer_defaults_disabled(self):
        """Test that empty layers default to enabled=False."""
        merged = merge_layers_with_config(self.layers, None, self.defaults)

        empty_layer = next(l for l in merged if l["layer_id"] == "layer4")
        self.assertFalse(empty_layer["enabled"])

    def test_visible_layers_defaults_enabled(self):
        """Test that visible layers with curves default to enabled=True."""
        merged = merge_layers_with_config(self.layers, None, self.defaults)

        visible_layer = next(l for l in merged if l["layer_id"] == "layer1")
        self.assertTrue(visible_layer["enabled"])

    def test_saved_config_overrides_defaults(self):
        """Test that saved config values override defaults."""
        saved = {
            "layers": {
                "layer1": {
                    "enabled": False,
                    "laser_mode": "M4",
                    "laser_power": 500,
                    "cutting_speed": 1500,
                }
            }
        }
        merged = merge_layers_with_config(self.layers, saved, self.defaults)

        layer1 = next(l for l in merged if l["layer_id"] == "layer1")
        self.assertFalse(layer1["enabled"])
        self.assertEqual(layer1["laser_mode"], "M4")
        self.assertEqual(layer1["laser_power"], 500)
        self.assertEqual(layer1["cutting_speed"], 1500)

    def test_saved_order_preserved(self):
        """Test that layer order from saved config is preserved."""
        saved = {
            "layer_order": ["layer2", "layer1"],  # Reverse of DOM order
            "layers": {
                "layer1": {},
                "layer2": {},
            }
        }
        merged = merge_layers_with_config(self.layers, saved, self.defaults)

        # layer2 should come first due to saved order
        self.assertEqual(merged[0]["layer_id"], "layer2")
        self.assertEqual(merged[1]["layer_id"], "layer1")

    def test_new_layers_appended(self):
        """Test that new layers not in saved config are appended."""
        saved = {
            "layer_order": ["layer1"],
            "layers": {"layer1": {}},
        }
        merged = merge_layers_with_config(self.layers, saved, self.defaults)

        # layer1 first (saved), then layer2, layer3, layer4 (new)
        self.assertEqual(merged[0]["layer_id"], "layer1")
        self.assertIn("layer2", [l["layer_id"] for l in merged[1:]])

    def test_japanese_layer_names(self):
        """Test that Japanese layer names are handled correctly."""
        root_jp = ElementTree.fromstring(TEST_SVG_JP)
        layers_jp = parse_layers(root_jp, canvas_height=300)

        merged = merge_layers_with_config(layers_jp, None, self.defaults)

        labels = [l["label"] for l in merged]
        self.assertIn("彫刻レイヤー", labels)
        self.assertIn("カットレイヤー", labels)


class TestCreateConfigDict(unittest.TestCase):
    """Test create_config_dict function."""

    def test_basic_config_creation(self):
        """Test creating config dict from layer configs."""
        layers = [
            {
                "layer_id": "layer1",
                "label": "Engrave",
                "enabled": True,
                "laser_mode": "M4",
                "laser_power": 400,
                "cutting_speed": 2000,
                "travel_speed": 3000,
                "passes": 1,
                "preset": "Engrave",
            },
            {
                "layer_id": "layer2",
                "label": "Cut",
                "enabled": True,
                "laser_mode": "M3",
                "laser_power": 900,
                "cutting_speed": 300,
                "travel_speed": 3000,
                "passes": 3,
                "preset": "Cut",
            },
        ]

        config = create_config_dict(
            layers, "combined", "top_to_bottom",
            "/output/dir", "output.gcode", True
        )

        self.assertEqual(config["output_mode"], "combined")
        self.assertEqual(config["add_numeric_suffix"], True)
        self.assertEqual(config["layer_order"], ["layer1", "layer2"])
        self.assertIn("layer1", config["layers"])
        self.assertIn("layer2", config["layers"])

        # Check that only saved keys are in layers (not curve_count, text_count, etc.)
        for layer_config in config["layers"].values():
            self.assertNotIn("curve_count", layer_config)
            self.assertNotIn("text_count", layer_config)
            self.assertNotIn("visible", layer_config)


class TestLayerPresets(unittest.TestCase):
    """Test LAYER_PRESETS constants."""

    def test_presets_exist(self):
        """Test that all expected presets exist."""
        self.assertIn("Custom", LAYER_PRESETS)
        self.assertIn("Engrave", LAYER_PRESETS)
        self.assertIn("Cut", LAYER_PRESETS)

    def test_preset_structure(self):
        """Test that presets have all required keys."""
        required_keys = ["laser_mode", "laser_power", "cutting_speed", "travel_speed", "passes", "pass_depth"]
        for preset_name, preset in LAYER_PRESETS.items():
            for key in required_keys:
                self.assertIn(key, preset, f"Preset {preset_name} missing key {key}")

    def test_engrave_preset(self):
        """Test Engrave preset values."""
        engrave = LAYER_PRESETS["Engrave"]
        self.assertEqual(engrave["laser_mode"], "M4")
        self.assertEqual(engrave["laser_power"], 400)
        self.assertEqual(engrave["cutting_speed"], 2000)

    def test_cut_preset(self):
        """Test Cut preset values."""
        cut = LAYER_PRESETS["Cut"]
        self.assertEqual(cut["laser_mode"], "M3")
        self.assertEqual(cut["laser_power"], 900)
        self.assertEqual(cut["cutting_speed"], 300)
        self.assertEqual(cut["passes"], 3)


class TestLayerDialogResult(unittest.TestCase):
    """Test LayerDialogResult dataclass."""

    def test_default_values(self):
        """Test default values of LayerDialogResult."""
        result = LayerDialogResult()
        self.assertFalse(result.confirmed)
        self.assertEqual(result.output_mode, "combined")
        self.assertEqual(result.layer_order, "top_to_bottom")
        self.assertEqual(result.output_dir, "")
        self.assertEqual(result.base_filename, "output.gcode")
        self.assertTrue(result.add_numeric_suffix)
        self.assertEqual(result.jobs, [])
        self.assertEqual(result.config_dict, {})

    def test_custom_values(self):
        """Test LayerDialogResult with custom values."""
        job = LayerJob(layer_id="test", label="Test", curves=[])
        result = LayerDialogResult(
            confirmed=True,
            output_mode="separate",
            layer_order="bottom_to_top",
            output_dir="/tmp",
            base_filename="test.gcode",
            add_numeric_suffix=False,
            jobs=[job],
            config_dict={"test": "value"},
        )
        self.assertTrue(result.confirmed)
        self.assertEqual(result.output_mode, "separate")
        self.assertEqual(result.layer_order, "bottom_to_top")
        self.assertEqual(result.output_dir, "/tmp")
        self.assertEqual(result.base_filename, "test.gcode")
        self.assertFalse(result.add_numeric_suffix)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.config_dict, {"test": "value"})


class TestDialogLogic(unittest.TestCase):
    """Test dialog logic that can be tested without GUI."""

    def setUp(self):
        self.root = ElementTree.fromstring(TEST_SVG)
        self.layers = parse_layers(self.root, canvas_height=300)
        self.defaults = {
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

    def test_build_jobs_from_dialog_result(self):
        """Test building LayerJobs from dialog result."""
        # Create a mock result with config_dict
        result = LayerDialogResult(
            confirmed=True,
            output_mode="combined",
            layer_order="top_to_bottom",
            config_dict={
                "layers": {
                    "layer1": {
                        "enabled": True,
                        "laser_mode": "M4",
                        "laser_power": 400,
                        "cutting_speed": 2000,
                        "travel_speed": 3000,
                        "passes": 1,
                        "pass_depth": 0.0,
                    },
                    "layer2": {
                        "enabled": False,  # Disabled
                        "laser_mode": "M3",
                        "laser_power": 900,
                        "cutting_speed": 300,
                        "travel_speed": 3000,
                        "passes": 3,
                        "pass_depth": 0.0,
                    },
                }
            }
        )

        jobs = build_jobs_from_dialog_result(result, self.layers)

        self.assertEqual(len(jobs), 1)  # Only layer1 is enabled
        self.assertEqual(jobs[0].layer_id, "layer1")
        self.assertEqual(jobs[0].laser_mode, "M4")
        self.assertEqual(jobs[0].laser_power, 400)
        self.assertEqual(jobs[0].cutting_speed, 2000)

    def test_build_jobs_respects_layer_order(self):
        """Test that layer_order is respected in job building."""
        result = LayerDialogResult(
            confirmed=True,
            layer_order="bottom_to_top",  # Reverse
            config_dict={
                "layers": {
                    "layer1": {"enabled": True},
                    "layer2": {"enabled": True},
                }
            }
        )

        jobs = build_jobs_from_dialog_result(result, self.layers)

        # With bottom_to_top, the order should be reversed from the dialog's top_to_bottom
        # Dialog returns layers in top_to_bottom order, so bottom_to_top should reverse
        self.assertEqual(jobs[0].layer_id, "layer2")
        self.assertEqual(jobs[1].layer_id, "layer1")


class TestIntegration(unittest.TestCase):
    """Integration tests for the full config flow."""

    def test_full_config_flow_svg(self):
        """Test full flow: parse -> merge -> save to SVG -> load -> merge."""
        root = ElementTree.fromstring(TEST_SVG)
        layers = parse_layers(root, canvas_height=300)
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

        # Initial merge (no saved config)
        merged1 = merge_layers_with_config(layers, None, defaults)

        # Create config and save to SVG
        config = create_config_dict(
            merged1, "combined", "top_to_bottom",
            "/output", "test.gcode", True
        )
        save_config_to_svg(root, config)

        # Load from SVG and merge again
        loaded = load_config_from_svg(root)
        self.assertIsNotNone(loaded)

        merged2 = merge_layers_with_config(layers, loaded, defaults)

        # Should have same layer count
        self.assertEqual(len(merged1), len(merged2))

        # Check that layer1 has the Engrave preset values (from defaults since no saved)
        layer1 = next(l for l in merged2 if l["layer_id"] == "layer1")
        self.assertEqual(layer1["laser_mode"], "M3")  # Default

    def test_full_config_flow_json(self):
        """Test full flow with JSON file save/load."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            root = ElementTree.fromstring(TEST_SVG)
            layers = parse_layers(root, canvas_height=300)
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

            merged = merge_layers_with_config(layers, None, defaults)
            config = create_config_dict(
                merged, "separate", "bottom_to_top",
                "/output", "test.gcode", False
            )

            # Save to JSON
            save_config_to_json(temp_path, config)

            # Load and merge
            loaded = load_config_from_json(temp_path)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["output_mode"], "separate")
            self.assertEqual(loaded["add_numeric_suffix"], False)

            merged2 = merge_layers_with_config(layers, loaded, defaults)
            self.assertEqual(len(merged), len(merged2))

        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)