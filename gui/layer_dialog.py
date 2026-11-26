"""
Tkinter-based multi-layer configuration dialog for J-Tech Photonics Laser Tool.

Provides a GUI for configuring per-layer laser settings, output mode, and execution order.
Supports saving/loading configuration to/from SVG data attributes and JSON files.
"""

import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Tuple
from xml.etree import ElementTree

from svg_to_gcode.compiler import LayerJob
from svg_to_gcode.svg_parser import LayerData


# =============================================================================
# Preset Definitions
# =============================================================================

LAYER_PRESETS = {
    "Custom": {
        "description": "Custom settings",
        "laser_mode": "M3",
        "laser_power": 255,
        "cutting_speed": 750,
        "travel_speed": 3000,
        "passes": 1,
        "pass_depth": 0.0,
    },
    "Engrave": {
        "description": "Engraving (raster/vector)",
        "laser_mode": "M4",
        "laser_power": 400,
        "cutting_speed": 2000,
        "travel_speed": 3000,
        "passes": 1,
        "pass_depth": 0.0,
    },
    "Cut": {
        "description": "Cutting (vector)",
        "laser_mode": "M3",
        "laser_power": 900,
        "cutting_speed": 300,
        "travel_speed": 3000,
        "passes": 3,
        "pass_depth": 0.0,
    },
}


# =============================================================================
# Configuration Persistence (SVG data attributes / JSON)
# =============================================================================

CONFIG_ATTR = "data-laser-config"


def save_config_to_svg(root: ElementTree.Element, config_dict: dict) -> None:
    """
    Save configuration dictionary to SVG root element as JSON in data-laser-config attribute.

    :param root: SVG root element
    :param config_dict: Configuration dictionary to save
    """
    try:
        json_str = json.dumps(config_dict, ensure_ascii=False, separators=(",", ":"))
        root.set(CONFIG_ATTR, json_str)
    except (TypeError, ValueError) as e:
        # Silently ignore serialization errors
        pass


def load_config_from_svg(root: ElementTree.Element) -> Optional[dict]:
    """
    Load configuration from SVG root element's data-laser-config attribute.

    :param root: SVG root element
    :return: Configuration dictionary or None if not found/invalid
    """
    json_str = root.get(CONFIG_ATTR)
    if not json_str:
        return None
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None


def _get_defaults_from_options(options: Any) -> dict:
    """Extract default settings from laser.py options object."""
    return {
        "travel_speed": getattr(options, "travel_speed", 3000.0),
        "cutting_speed": getattr(options, "cutting_speed", 750.0),
        "passes": getattr(options, "passes", 1),
        "pass_depth": getattr(options, "pass_depth", 1.0),
        "laser_mode": "M3",
        "laser_power": 255,
        "laser_off_command": getattr(options, "tool_off_command", "M5;"),
        "laser_power_command": getattr(options, "tool_power_command", "M3 S255;"),
        "dwell_time": getattr(options, "dwell_time", 0.0),
        "unit": getattr(options, "unit", "mm"),
    }


def merge_layers_with_config(
    layers: List[LayerData],
    saved_config: Optional[dict],
    defaults: dict,
) -> List[dict]:
    """
    Merge parsed layers with saved configuration and defaults.

    :param layers: List of LayerData from parse_layers
    :param saved_config: Previously saved configuration dict (from SVG or JSON)
    :param defaults: Default settings dict (from laser.inx options)
    :return: List of layer job config dicts ready for LayerJob creation
    """
    if saved_config is None:
        saved_config = {}

    saved_layers = saved_config.get("layers", {})
    saved_order = saved_config.get("layer_order", [])
    saved_output_mode = saved_config.get("output_mode", "combined")
    saved_add_suffix = saved_config.get("add_numeric_suffix", True)

    # Build layer_id -> index mapping for current layers
    current_layer_ids = [layer.layer_id for layer in layers]

    # Create result list preserving saved order where possible
    result = []
    processed_ids = set()

    # First, add layers in saved order (if they exist in current layers)
    for saved_id in saved_order:
        if saved_id in current_layer_ids:
            layer = next(l for l in layers if l.layer_id == saved_id)
            layer_config = _build_layer_config(layer, saved_layers.get(saved_id), defaults)
            result.append(layer_config)
            processed_ids.add(saved_id)

    # Then, add remaining layers in current DOM order
    for layer in layers:
        if layer.layer_id not in processed_ids:
            layer_config = _build_layer_config(layer, saved_layers.get(layer.layer_id), defaults)
            result.append(layer_config)

    return result


def _build_layer_config(
    layer: LayerData,
    saved_layer: Optional[dict],
    defaults: dict,
) -> dict:
    """Build a single layer's job configuration."""
    # Determine initial enabled state
    if not layer.visible or len(layer.curves) == 0:
        initial_enabled = False
    else:
        initial_enabled = saved_layer.get("enabled", True) if saved_layer else True

    # Start with defaults
    config = {
        "layer_id": layer.layer_id,
        "label": layer.label,
        "enabled": initial_enabled,
        "laser_mode": defaults.get("laser_mode", "M3"),
        "laser_power": defaults.get("laser_power", 255),
        "laser_off_command": defaults.get("laser_off_command", "M5;"),
        "laser_power_command": None,  # Default to None (use laser_mode + laser_power)
        "travel_speed": defaults.get("travel_speed", 3000.0),
        "cutting_speed": defaults.get("cutting_speed", 750.0),
        "passes": defaults.get("passes", 1),
        "pass_depth": defaults.get("pass_depth", 0.0),
        "dwell_time": defaults.get("dwell_time", 0.0),
        "preset": "Custom",
        "curve_count": len(layer.curves),
        "text_count": layer.unconverted_text_count,
        "visible": layer.visible,
    }

    # Override with saved values if available
    if saved_layer:
        for key in config:
            if key in saved_layer and key not in ("layer_id", "label", "curve_count", "text_count", "visible"):
                config[key] = saved_layer[key]

    return config


def create_config_dict(
    layers: List[dict],
    output_mode: str,
    layer_order: str,
    output_dir: str,
    base_filename: str,
    add_numeric_suffix: bool,
) -> dict:
    """Create a complete configuration dictionary for saving."""
    layers_data = {}
    layer_order_list = [l["layer_id"] for l in layers]
    for layer in layers:
        # Only save user-adjustable settings, not computed fields
        saved_keys = [
            "enabled", "laser_mode", "laser_power", "laser_off_command",
            "laser_power_command", "travel_speed", "cutting_speed",
            "passes", "pass_depth", "dwell_time", "preset",
        ]
        layers_data[layer["layer_id"]] = {
            k: layer[k] for k in saved_keys if k in layer
        }

    return {
        "layers": layers_data,
        "layer_order": layer_order_list,
        "output_mode": output_mode,
        "add_numeric_suffix": add_numeric_suffix,
    }


def save_config_to_json(file_path: str, config: dict) -> None:
    """Save configuration to JSON file."""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def load_config_from_json(file_path: str) -> Optional[dict]:
    """Load configuration from JSON file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError, OSError):
        return None


# =============================================================================
# Result Data Class
# =============================================================================

@dataclass
class LayerDialogResult:
    """Result of the layer configuration dialog."""
    confirmed: bool = False
    output_mode: str = "combined"  # "combined" or "separate"
    layer_order: str = "top_to_bottom"  # "top_to_bottom" or "bottom_to_top"
    output_dir: str = ""
    base_filename: str = "output.gcode"
    add_numeric_suffix: bool = True
    jobs: List[LayerJob] = field(default_factory=list)
    config_dict: dict = field(default_factory=dict)


# =============================================================================
# Tkinter Dialog Implementation
# =============================================================================

class _LayerRow:
    """Represents a single layer's UI row in the dialog."""

    def __init__(
        self,
        parent: ttk.Frame,
        layer_config: dict,
        row_idx: int,
        on_move_up: callable,
        on_move_down: callable,
        on_preset_change: callable,
        on_delete: callable,
        presets: dict,
    ):
        self.layer_config = layer_config
        self.row_idx = row_idx
        self.on_move_up = on_move_up
        self.on_move_down = on_move_down
        self.on_preset_change = on_preset_change
        self.presets = presets
        self.widgets = {}

        self._build_ui(parent, row_idx, on_delete)

    def _build_ui(self, parent: ttk.Frame, row_idx: int, on_delete: callable) -> None:
        """Build the UI widgets for this layer row."""
        row_frame = ttk.Frame(parent)
        row_frame.grid(row=row_idx, column=0, sticky="ew", pady=2, padx=4)
        row_frame.columnconfigure(2, weight=1)

        # Enable checkbox
        self.enabled_var = tk.BooleanVar(value=self.layer_config.get("enabled", True))
        self.widgets["enabled"] = ttk.Checkbutton(
            row_frame, variable=self.enabled_var,
            state="normal" if self.layer_config.get("curve_count", 0) > 0 else "disabled"
        )
        self.widgets["enabled"].grid(row=0, column=0, padx=2)

        # Layer name with curve count and text warning
        curve_count = self.layer_config.get("curve_count", 0)
        text_count = self.layer_config.get("text_count", 0)
        name_text = self.layer_config.get("label", "")
        if curve_count > 0:
            name_text += f" ({curve_count} curves)"
        if text_count > 0:
            name_text += f" ⚠ 未変換テキスト({text_count})"
            name_label = ttk.Label(row_frame, text=name_text, foreground="red")
        else:
            name_label = ttk.Label(row_frame, text=name_text)
        name_label.grid(row=0, column=1, sticky="w", padx=4)
        self.widgets["name"] = name_label

        # Preset combobox
        self.preset_var = tk.StringVar(value=self.layer_config.get("preset", "Custom"))
        self.widgets["preset"] = ttk.Combobox(
            row_frame, textvariable=self.preset_var,
            values=list(self.presets.keys()), width=10, state="readonly"
        )
        self.widgets["preset"].grid(row=0, column=2, padx=2)
        self.widgets["preset"].bind("<<ComboboxSelected>>",
                                     lambda e: self.on_preset_change(self))

        # Laser mode
        self.mode_var = tk.StringVar(value=self.layer_config.get("laser_mode", "M3"))
        self.widgets["mode"] = ttk.Combobox(
            row_frame, textvariable=self.mode_var,
            values=["M3", "M4"], width=4, state="readonly"
        )
        self.widgets["mode"].grid(row=0, column=3, padx=2)

        # Laser power (S value)
        self.power_var = tk.StringVar(value=str(self.layer_config.get("laser_power", 255)))
        self.widgets["power"] = ttk.Entry(row_frame, textvariable=self.power_var, width=6)
        self.widgets["power"].grid(row=0, column=4, padx=2)

        # Cutting speed
        self.cut_speed_var = tk.StringVar(value=str(self.layer_config.get("cutting_speed", 750)))
        self.widgets["cut_speed"] = ttk.Entry(row_frame, textvariable=self.cut_speed_var, width=6)
        self.widgets["cut_speed"].grid(row=0, column=5, padx=2)

        # Travel speed
        self.travel_speed_var = tk.StringVar(value=str(self.layer_config.get("travel_speed", 3000)))
        self.widgets["travel_speed"] = ttk.Entry(row_frame, textvariable=self.travel_speed_var, width=6)
        self.widgets["travel_speed"].grid(row=0, column=6, padx=2)

        # Passes
        self.passes_var = tk.StringVar(value=str(self.layer_config.get("passes", 1)))
        self.widgets["passes"] = ttk.Entry(row_frame, textvariable=self.passes_var, width=4)
        self.widgets["passes"].grid(row=0, column=7, padx=2)

    def get_values(self) -> dict:
        """Get current values from widgets."""
        return {
            "enabled": self.enabled_var.get(),
            "preset": self.preset_var.get(),
            "laser_mode": self.mode_var.get(),
            "laser_power": int(self.power_var.get()) if self.power_var.get() else 255,
            "cutting_speed": float(self.cut_speed_var.get()) if self.cut_speed_var.get() else 750,
            "travel_speed": float(self.travel_speed_var.get()) if self.travel_speed_var.get() else 3000,
            "passes": int(self.passes_var.get()) if self.passes_var.get() else 1,
        }

    def apply_preset(self, preset_name: str) -> None:
        """Apply preset values to this row's variables."""
        if preset_name not in self.presets:
            return
        preset = self.presets[preset_name]
        self.preset_var.set(preset_name)
        self.mode_var.set(preset["laser_mode"])
        self.power_var.set(str(preset["laser_power"]))
        self.cut_speed_var.set(str(preset["cutting_speed"]))
        self.travel_speed_var.set(str(preset["travel_speed"]))
        self.passes_var.set(str(preset["passes"]))
        # Update the underlying config
        self.layer_config.update({
            "preset": preset_name,
            "laser_mode": preset["laser_mode"],
            "laser_power": preset["laser_power"],
            "cutting_speed": preset["cutting_speed"],
            "travel_speed": preset["travel_speed"],
            "passes": preset["passes"],
        })

    def set_move_buttons_state(self, can_move_up: bool, can_move_down: bool) -> None:
        """No-op kept for backward compatibility (layer ordering UI removed)."""
        pass


class LayerConfigDialog:
    """Main dialog for multi-layer configuration."""

    def __init__(
        self,
        parent: tk.Tk,
        layers: List[LayerData],
        defaults: dict,
        saved_config: Optional[dict] = None,
        output_dir: str = "",
        base_filename: str = "output.gcode",
        add_numeric_suffix: bool = True,
        unit: str = "mm",
        bed_width: float = 200,
        bed_height: float = 200,
    ):
        self.parent = parent
        self.result = LayerDialogResult()
        self.layers_config = merge_layers_with_config(layers, saved_config, defaults)
        self.defaults = defaults
        self.unit = unit
        self.bed_width = bed_width
        self.bed_height = bed_height

        self.output_dir_var = tk.StringVar(value=output_dir)
        self.base_filename_var = tk.StringVar(value=base_filename)
        self.add_suffix_var = tk.BooleanVar(value=add_numeric_suffix)
        self.output_mode_var = tk.StringVar(value="separate")
        self.layer_order_var = tk.StringVar(value="top_to_bottom")

        self.row_widgets: List[_LayerRow] = []

        self._build_dialog()

    def _build_dialog(self) -> None:
        """Build the complete dialog UI."""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("J-Tech Laser Tool - Multi-Layer Configuration")
        self.dialog.geometry("820x460")
        self.dialog.minsize(720, 360)
        self.dialog.attributes("-topmost", True)

        # Make it modal when parent is visible; bind window close to cancel
        if self.parent.winfo_viewable():
            self.dialog.transient(self.parent)
        self.dialog.grab_set()
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Configure grid weights
        self.dialog.columnconfigure(0, weight=1)
        self.dialog.rowconfigure(1, weight=1)  # Layer list area

        # ===== Top: Global Settings =====
        top_frame = ttk.LabelFrame(self.dialog, text="Global Settings", padding=8)
        top_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=4)
        top_frame.columnconfigure(1, weight=1)
        top_frame.columnconfigure(3, weight=1)
        top_frame.columnconfigure(5, weight=1)

        # Output directory (read-only display of Inkscape extension setting)
        ttk.Label(top_frame, text="Output Dir:").grid(row=0, column=0, sticky="w", padx=4)
        dir_entry = ttk.Entry(top_frame, textvariable=self.output_dir_var, state="readonly")
        dir_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=4)

        # Base filename (read-only display of Inkscape extension setting)
        ttk.Label(top_frame, text="Planned Filename:").grid(row=0, column=3, sticky="w", padx=4)
        ttk.Entry(top_frame, textvariable=self.base_filename_var, width=24, state="readonly").grid(row=0, column=4, sticky="ew", padx=4)

        # Add numeric suffix indicator (read-only)
        suffix_text = "Auto Suffix: ON" if self.add_suffix_var.get() else "Auto Suffix: OFF"
        ttk.Label(top_frame, text=suffix_text).grid(row=0, column=5, padx=8)

        # Output mode & bed info (read-only)
        info_frame = ttk.Frame(top_frame)
        info_frame.grid(row=1, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Label(
            info_frame,
            text=f"Output Mode: Separate Files per Layer  |  Unit: {self.unit}  |  Bed: {self.bed_width}×{self.bed_height} {self.unit}"
        ).pack(side=tk.LEFT)

        # ===== Middle: Layer List (Scrollable) =====
        list_frame = ttk.LabelFrame(self.dialog, text="Layers", padding=4)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        # Canvas with scrollbar for scrolling
        self.canvas = tk.Canvas(list_frame, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        # Bind mousewheel
        self.canvas.bind("<Enter>", lambda e: self._bind_mousewheel())
        self.canvas.bind("<Leave>", lambda e: self._unbind_mousewheel())
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Column headers
        header_frame = ttk.Frame(self.scrollable_frame)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        headers = [
            ("Enabled", 0, 7),
            ("Layer Name", 1, 28),
            ("Preset", 2, 10),
            ("Mode", 3, 5),
            ("S (Power)", 4, 8),
            ("F (Cut)", 5, 8),
            ("F (Travel)", 6, 8),
            ("Passes", 7, 6),
        ]
        for text, col, width in headers:
            lbl = ttk.Label(header_frame, text=text, font=("TkDefaultFont", 8, "bold"), width=width, anchor="center")
            lbl.grid(row=0, column=col, padx=2)

        # Layer rows will be added by _rebuild_layer_rows()

        # ===== Bottom: Action Buttons =====
        bottom_frame = ttk.Frame(self.dialog, padding=8)
        bottom_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        bottom_frame.columnconfigure(0, weight=1)

        # Left: JSON import/export
        left_actions = ttk.Frame(bottom_frame)
        left_actions.grid(row=0, column=0, sticky="w")
        ttk.Button(left_actions, text="Load JSON...", command=self._load_json).pack(side=tk.LEFT, padx=4)
        ttk.Button(left_actions, text="Save JSON...", command=self._save_json).pack(side=tk.LEFT, padx=4)

        # Right: Cancel / Execute (enlarged buttons for better usability)
        style = ttk.Style(self.dialog)
        style.configure("Action.TButton", font=("TkDefaultFont", 10), padding=(12, 6))
        style.configure("Execute.TButton", font=("TkDefaultFont", 10, "bold"), padding=(18, 8))

        right_actions = ttk.Frame(bottom_frame)
        right_actions.grid(row=0, column=1, sticky="e")
        ttk.Button(right_actions, text="Cancel", style="Action.TButton", command=self._on_cancel).pack(side=tk.LEFT, padx=6)
        self.execute_btn = ttk.Button(right_actions, text="Generate G-code", style="Execute.TButton", command=self._on_execute)
        self.execute_btn.pack(side=tk.LEFT, padx=6)

        # Initial layer rows
        self._rebuild_layer_rows()

    def _rebuild_layer_rows(self) -> None:
        """Rebuild all layer rows in current order."""
        # Clear existing widgets (except header at row 0)
        for widget in self.scrollable_frame.winfo_children():
            if isinstance(widget, ttk.Frame) and widget.grid_info().get("row", 0) > 0:
                widget.destroy()

        self.row_widgets.clear()

        # Determine order based on layer_order_var
        if self.layer_order_var.get() == "top_to_bottom":
            ordered_configs = list(reversed(self.layers_config))
        else:
            ordered_configs = list(self.layers_config)

        for idx, layer_config in enumerate(ordered_configs):
            row = _LayerRow(
                self.scrollable_frame, layer_config, idx + 1,  # +1 for header row
                on_move_up=lambda r: self._move_row(r, -1),
                on_move_down=lambda r: self._move_row(r, 1),
                on_preset_change=lambda r: self._on_preset_change(r),
                on_delete=lambda r: self._delete_row(r),
                presets=LAYER_PRESETS,
            )
            self.row_widgets.append(row)

        self._update_move_buttons()

    def _sync_rows_to_configs(self) -> None:
        """Persist current UI row edits back into layer_config dicts before rebuilding."""
        for row in self.row_widgets:
            cfg = row.layer_config
            cfg["enabled"] = row.enabled_var.get()
            cfg["preset"] = row.preset_var.get()
            cfg["laser_mode"] = row.mode_var.get()
            try:
                cfg["laser_power"] = int(row.power_var.get())
            except ValueError:
                pass
            try:
                cfg["cutting_speed"] = float(row.cut_speed_var.get())
            except ValueError:
                pass
            try:
                cfg["travel_speed"] = float(row.travel_speed_var.get())
            except ValueError:
                pass
            try:
                cfg["passes"] = int(row.passes_var.get())
            except ValueError:
                pass

    def _move_row(self, row: _LayerRow, direction: int) -> None:
        """Move a row up (-1) or down (+1) in the list."""
        current_idx = self.row_widgets.index(row)
        new_idx = current_idx + direction
        if 0 <= new_idx < len(self.row_widgets):
            self._sync_rows_to_configs()
            n = len(self.layers_config)
            if self.layer_order_var.get() == "top_to_bottom":
                cfg_idx = n - 1 - current_idx
                cfg_new_idx = n - 1 - new_idx
            else:
                cfg_idx = current_idx
                cfg_new_idx = new_idx
            self.layers_config[cfg_idx], self.layers_config[cfg_new_idx] = (
                self.layers_config[cfg_new_idx],
                self.layers_config[cfg_idx],
            )
            self._rebuild_layer_rows()

    def _delete_row(self, row: _LayerRow) -> None:
        """Delete a row (not used currently, but hook exists)."""
        pass

    def _on_preset_change(self, row: _LayerRow) -> None:
        """Handle preset selection change."""
        row.apply_preset(row.preset_var.get())

    def _update_move_buttons(self) -> None:
        """Enable/disable move buttons based on position."""
        for idx, row in enumerate(self.row_widgets):
            row.set_move_buttons_state(idx > 0, idx < len(self.row_widgets) - 1)

    def _on_output_mode_change(self) -> None:
        """Handle output mode radio button change."""
        pass  # No immediate action needed

    def _on_layer_order_change(self) -> None:
        """Handle layer order radio button change - rebuild rows."""
        self._sync_rows_to_configs()
        self._rebuild_layer_rows()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        """Adjust scrollable frame width to match canvas."""
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _bind_mousewheel(self) -> None:
        """Bind mousewheel to canvas scrolling."""
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self) -> None:
        """Unbind mousewheel."""
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        """Handle mousewheel scrolling."""
        if event.num == 4 or event.delta > 0:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            self.canvas.yview_scroll(1, "units")

    def _browse_output_dir(self) -> None:
        """Open directory chooser for output directory."""
        dir_path = filedialog.askdirectory(
            parent=self.dialog,
            title="Select Output Directory",
            initialdir=self.output_dir_var.get() or "."
        )
        if dir_path:
            self.output_dir_var.set(dir_path)

    def _load_json(self) -> None:
        """Load configuration from JSON file."""
        file_path = filedialog.askopenfilename(
            parent=self.dialog,
            title="Load Configuration JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if file_path:
            config = load_config_from_json(file_path)
            if config:
                self.layers_config = merge_layers_with_config(
                    # We need to reconstruct LayerData objects - for now just use saved data
                    # This is a simplified version; full implementation would need LayerData
                    [], config, self.defaults
                )
                self.output_mode_var.set(config.get("output_mode", "combined"))
                self.add_suffix_var.set(config.get("add_numeric_suffix", True))
                self._rebuild_layer_rows()
                messagebox.showinfo("Success", "Configuration loaded from JSON")
            else:
                messagebox.showerror("Error", "Failed to load JSON configuration")

    def _save_json(self) -> None:
        """Save current configuration to JSON file."""
        file_path = filedialog.asksaveasfilename(
            parent=self.dialog,
            title="Save Configuration JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if file_path:
            config = create_config_dict(
                [r.layer_config for r in self.row_widgets],
                self.output_mode_var.get(),
                self.layer_order_var.get(),
                self.output_dir_var.get(),
                self.base_filename_var.get(),
                self.add_suffix_var.get(),
            )
            save_config_to_json(file_path, config)
            messagebox.showinfo("Success", "Configuration saved to JSON")

    def _validate_inputs(self) -> bool:
        """Validate all numeric inputs."""
        for row in self.row_widgets:
            try:
                int(row.power_var.get())
                float(row.cut_speed_var.get())
                float(row.travel_speed_var.get())
                int(row.passes_var.get())
            except ValueError:
                messagebox.showerror("Invalid Input", f"Layer '{row.layer_config['label']}' has invalid numeric values.")
                return False
        return True

    def _on_execute(self) -> None:
        """Handle execute button - validate and build result."""
        if not self._validate_inputs():
            return

        # Build LayerJob list
        jobs = []
        for row in self.row_widgets:
            values = row.get_values()
            if values["enabled"] and row.layer_config.get("curve_count", 0) > 0:
                # Find the original LayerData to get curves
                # This is a simplification - in real implementation we'd match by layer_id
                pass

        # Check at least one enabled layer with curves
        enabled_with_curves = any(
            r.get_values()["enabled"] and r.layer_config.get("curve_count", 0) > 0
            for r in self.row_widgets
        )
        if not enabled_with_curves:
            if not messagebox.askyesno("Warning",
                "No enabled layers with curves. Continue anyway?"):
                return

        # Build result
        self.result = LayerDialogResult(
            confirmed=True,
            output_mode=self.output_mode_var.get(),
            layer_order=self.layer_order_var.get(),
            output_dir=self.output_dir_var.get(),
            base_filename=self.base_filename_var.get(),
            add_numeric_suffix=self.add_suffix_var.get(),
            jobs=[],  # Filled in by caller based on row values
            config_dict=create_config_dict(
                [r.layer_config for r in self.row_widgets],
                self.output_mode_var.get(),
                self.layer_order_var.get(),
                self.output_dir_var.get(),
                self.base_filename_var.get(),
                self.add_suffix_var.get(),
            ),
        )
        self.dialog.destroy()

    def _on_cancel(self) -> None:
        """Handle cancel button."""
        self.result = LayerDialogResult(confirmed=False)
        self.dialog.destroy()

    def show(self) -> LayerDialogResult:
        """Show dialog and wait for result."""
        self.parent.wait_window(self.dialog)
        return self.result


def show_layer_dialog(
    parent: Optional[tk.Tk],
    layers: List[LayerData],
    defaults: dict,
    saved_config: Optional[dict] = None,
    output_dir: str = "",
    base_filename: str = "output.gcode",
    add_numeric_suffix: bool = True,
    unit: str = "mm",
    bed_width: float = 200,
    bed_height: float = 200,
) -> LayerDialogResult:
    """
    Show the multi-layer configuration dialog.

    :param parent: Parent Tk window (if None, creates and cleans up a temporary hidden root)
    :param layers: List of LayerData from parse_layers
    :param defaults: Default settings from laser.inx options
    :param saved_config: Previously saved configuration (from SVG or JSON)
    :param output_dir: Initial output directory
    :param base_filename: Initial base filename
    :param add_numeric_suffix: Initial add numeric suffix setting
    :param unit: Unit (mm/in)
    :param bed_width: Bed width in units
    :param bed_height: Bed height in units
    :return: LayerDialogResult with user choices
    """
    owns_root = False
    if parent is None:
        parent = tk.Tk()
        parent.withdraw()
        owns_root = True

    try:
        dialog = LayerConfigDialog(
            parent, layers, defaults, saved_config,
            output_dir, base_filename, add_numeric_suffix,
            unit, bed_width, bed_height,
        )
        return dialog.show()
    finally:
        if owns_root:
            try:
                parent.destroy()
            except tk.TclError:
                pass


# =============================================================================
# Helper to build LayerJobs from dialog result (called by laser.py after dialog)
# =============================================================================

def build_jobs_from_dialog_result(
    result: LayerDialogResult,
    layers: List[LayerData],
) -> List[LayerJob]:
    """
    Build LayerJob objects from dialog result and parsed layers.

    :param result: LayerDialogResult from show_layer_dialog
    :param layers: Original LayerData list from parse_layers
    :return: List of LayerJob objects ready for MultiLayerCompiler
    """
    # Create mapping from layer_id to LayerData
    layer_map = {layer.layer_id: layer for layer in layers}

    # Create mapping from layer_id to row config from result
    # config_dict["layers"] is a dict with layer_id as key
    layers_config = result.config_dict.get("layers", {})

    # Determine job order from saved layer_order, or fall back to config dict order
    saved_order = result.config_dict.get("layer_order", [])
    if saved_order:
        # Use saved order, filtering to only layers present in config
        ordered_layer_ids = [lid for lid in saved_order if lid in layers_config]
    else:
        # Fall back to config dict insertion order
        ordered_layer_ids = list(layers_config.keys())

    jobs = []
    for layer_id in ordered_layer_ids:
        row_config = layers_config.get(layer_id)
        if row_config is None:
            continue
        layer_data = layer_map.get(layer_id)
        if layer_data is None:
            continue

        # Skip disabled layers
        if not row_config.get("enabled", True):
            continue

        # Skip layers with no curves
        if len(layer_data.curves) == 0:
            continue

        job = LayerJob(
            layer_id=layer_id,
            label=layer_data.label,
            curves=layer_data.curves,
            enabled=row_config.get("enabled", True),
            laser_mode=row_config.get("laser_mode", "M3"),
            laser_power=row_config.get("laser_power", 255),
            laser_off_command=row_config.get("laser_off_command", "M5;"),
            laser_power_command=row_config.get("laser_power_command"),
            travel_speed=row_config.get("travel_speed", 3000.0),
            cutting_speed=row_config.get("cutting_speed", 750.0),
            passes=row_config.get("passes", 1),
            pass_depth=row_config.get("pass_depth", 0.0),
            dwell_time=row_config.get("dwell_time", 0.0),
        )
        jobs.append(job)

    # Apply ordering from result.layer_order (dialog setting)
    # This reverses the list if needed
    if result.layer_order == "bottom_to_top":
        jobs.reverse()
    # If top_to_bottom, keep as-is (saved order is already top-to-bottom)

    return jobs