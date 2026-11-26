"""
GUI package for J-Tech Photonics Laser Tool multi-layer configuration.
"""

from gui.layer_dialog import (
    LayerDialogResult,
    LayerConfigDialog,
    show_layer_dialog,
    save_config_to_svg,
    load_config_from_svg,
    merge_layers_with_config,
    create_config_dict,
    save_config_to_json,
    load_config_from_json,
    LAYER_PRESETS,
    build_jobs_from_dialog_result,
)
