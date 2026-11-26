"""
Multi-layer G-code compiler for laser cutting/engraving.

This module provides a compiler that can handle multiple LayerJob objects,
each with its own laser settings, and output either a single combined G-code
file or separate files per layer.
"""

import os
import warnings
import re
import typing
from dataclasses import dataclass, field
from typing import List, Optional, Union

from svg_to_gcode.compiler import Compiler
from svg_to_gcode.compiler.interfaces import Gcode
from svg_to_gcode.geometry import Curve, Line
from svg_to_gcode.geometry import LineSegmentChain
from svg_to_gcode import UNITS, TOLERANCES


def sanitize_filename(name: str) -> str:
    
    r"""
    Sanitize a string for use as a filename on Windows.
    
    Replaces forbidden characters (\ / : * ? " < > |), spaces, and control characters
    with underscore. Strips leading/trailing whitespace and dots.
    Returns "layer" if the result is empty.
    """
    if not name:
        return "layer"
    
    # Strip leading/trailing whitespace and dots FIRST
    sanitized = name.strip(' .')
    
    # Replace Windows forbidden characters, spaces, and control characters
    # Forbidden: \ / : * ? " < > | and space
    sanitized = re.sub(r'[\\/:*?"<>| \x00-\x1f\x7f]', '_', sanitized)
    
    # Collapse multiple underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    
    if not sanitized:
        return "layer"
    
    return sanitized


@dataclass
class LayerJob:
    """
    Represents a single layer's compilation job with its own settings.
    
    :param layer_id: The SVG id attribute of the layer.
    :param label: The display label of the layer.
    :param curves: List of geometric curves to compile for this layer.
    :param enabled: Whether this job should be processed.
    :param laser_mode: Laser mode - "M3" (constant power) or "M4" (dynamic power).
    :param laser_power: Laser power S-value (0+). Not clamped to 255.
    :param laser_off_command: Command to turn laser off (default "M5;").
    :param laser_power_command: Custom laser power command template. 
        If provided, used instead of f"{laser_mode} S{laser_power};".
        Supports \\n escape sequences for multi-line commands.
    :param travel_speed: Movement speed for non-cutting moves (G0/G1).
    :param cutting_speed: Cutting speed for laser-on moves.
    :param passes: Number of passes.
    :param pass_depth: Z-axis depth per pass (0 = no Z moves).
    :param dwell_time: Dwell time in milliseconds before moves.
    """
    layer_id: str
    label: str
    curves: List[Curve]
    enabled: bool = True
    laser_mode: str = "M3"
    laser_power: int = 255
    laser_off_command: str = "M5;"
    laser_power_command: Optional[str] = None
    travel_speed: float = 3000.0
    cutting_speed: float = 750.0
    passes: int = 1
    pass_depth: float = 0.0
    dwell_time: float = 0.0


def _expand_escapes(text: str) -> str:
    """Expand escape sequences like \\n, \\t in a string."""
    if not text:
        return text
    # Replace literal \n with actual newline, etc.
    return text.replace(r'\n', '\n').replace(r'\t', '\t').replace(r'\r', '\r')


class _JobGcodeInterface(Gcode):
    """
    Custom Gcode interface for a specific LayerJob.
    Overrides laser_off and set_laser_power with job-specific commands.
    """
    
    def __init__(self, job: LayerJob):
        super().__init__()
        self._job = job
    
    def laser_off(self) -> str:
        return _expand_escapes(self._job.laser_off_command)
    
    def set_laser_power(self, power: float) -> str:
        # power is 0-1, but we use job's laser_power (already scaled)
        if self._job.laser_power_command is not None:
            return _expand_escapes(self._job.laser_power_command)
        
        # Default: use laser_mode + laser_power
        # laser_power is already the S-value (e.g., 255, 1000, etc.)
        cmd = f"{self._job.laser_mode} S{self._job.laser_power};"
        return _expand_escapes(cmd)


class MultiLayerCompiler:
    """
    Compiler for multi-layer G-code generation.
    
    Supports two output modes:
    - Combined: single file with all enabled layers concatenated
    - Separate: one file per layer
    """
    
    def __init__(self, unit: str = "mm", custom_header: Optional[List[str]] = None,
                 custom_footer: Optional[List[str]] = None):
        """
        :param unit: "mm" or "in" - output unit for G21/G20
        :param custom_header: List of G-code commands to prepend to each file
        :param custom_footer: List of G-code commands to append to each file
        """
        if unit not in UNITS:
            raise ValueError(f"Unknown unit {unit}. Please specify one of: {UNITS}")
        
        self.unit = unit
        self.custom_header = custom_header or []
        self.custom_footer = custom_footer or []
    
    def _build_job_compiler(self, job: LayerJob) -> Compiler:
        """Build a Compiler instance configured for a specific LayerJob."""
        # Create custom interface for this job
        interface_class = lambda: _JobGcodeInterface(job)
        
        return Compiler(
            interface_class=interface_class,
            movement_speed=job.travel_speed,
            cutting_speed=job.cutting_speed,
            pass_depth=job.pass_depth,
            dwell_time=job.dwell_time,
            unit=self.unit,
            custom_header=[],  # We handle headers manually in combined/separate
            custom_footer=[],  # We handle footers manually
        )
    
    def _compile_job_body(self, job: LayerJob) -> List[str]:
        """Compile just the body (curves) for a single job, returning list of commands."""
        compiler = self._build_job_compiler(job)
        
        # Add curves - this populates compiler.body
        if job.curves:
            compiler.append_curves(job.curves)
        
        return compiler.body
    
    def compile_combined(self, jobs: List[LayerJob]) -> str:
        """
        Compile all enabled jobs into a single G-code string.
        
        :param jobs: List of LayerJob objects
        :return: Complete G-code as string
        """
        # Filter enabled jobs with curves
        active_jobs = [j for j in jobs if j.enabled and j.curves]
        
        if not active_jobs:
            warnings.warn("No enabled jobs with curves to compile.")
            return ""
        
        gcode = []
        
        # Common header
        gcode.append("G90;")  # Absolute coordinates
        gcode.append(f"{'G21;' if self.unit == 'mm' else 'G20;'}")  # Units
        
        # Custom header
        for cmd in self.custom_header:
            if cmd.strip():
                gcode.append(_expand_escapes(cmd))
        
        # Process each job
        for idx, job in enumerate(active_jobs):
            # Layer separator comment
            safe_label = job.label.replace('\n', ' ').replace('\r', '')
            gcode.append(f"; === Layer {idx + 1}: {safe_label} ===")
            
            # Compile job body with fresh compiler (resets position, speed)
            job_body = self._compile_job_body(job)
            
            if not job_body:
                warnings.warn(f"Job '{job.label}' produced empty body.")
                continue
            
            # Split body into initial setup and cutting commands
            # Setup ends at the laser power command (M3 S... or M4 S...)
            # Everything after that is cutting moves
            setup_end_idx = 0
            for i, cmd in enumerate(job_body):
                stripped = cmd.strip()
                if stripped.startswith(("M3 ", "M4 ")) and "S" in stripped:
                    # Laser power command found - setup ends here (inclusive)
                    setup_end_idx = i + 1
                    break
            
            setup_commands = job_body[:setup_end_idx]
            cutting_commands = job_body[setup_end_idx:]
            
            # Handle passes
            for pass_idx in range(job.passes):
                if pass_idx == 0:
                    # First pass: use full body (setup + cutting)
                    gcode.extend(job_body)
                else:
                    # Subsequent passes: laser off, Z move if needed, laser on, then cutting
                    gcode.append(_expand_escapes(job.laser_off_command))
                    
                    if job.pass_depth > 0:
                        temp_interface = _JobGcodeInterface(job)
                        temp_interface.set_movement_speed(job.travel_speed)
                        gcode.append(temp_interface.set_relative_coordinates())
                        gcode.append(temp_interface.linear_move(z=-job.pass_depth))
                        gcode.append(temp_interface.set_absolute_coordinates())
                    
                    # Turn laser on again for this pass
                    if setup_commands:
                        for cmd in reversed(setup_commands):
                            stripped = cmd.strip()
                            if stripped.startswith(("M3 ", "M4 ")) and "S" in stripped:
                                gcode.append(cmd)
                                break
                    
                    gcode.extend(cutting_commands)
            
            # After last pass of job, ensure laser is off
            gcode.append(_expand_escapes(job.laser_off_command))
        
        # Common footer
        for cmd in self.custom_footer:
            if cmd.strip():
                gcode.append(_expand_escapes(cmd))
        
        # Filter empty lines and join
        gcode = [cmd for cmd in gcode if cmd and cmd.strip()]
        
        return '\n'.join(gcode)
    
    def compile_combined_to_file(self, jobs: List[LayerJob], file_path: str) -> str:
        """
        Compile all enabled jobs and write to a single file.
        
        :param jobs: List of LayerJob objects
        :param file_path: Output file path
        :return: The file path written
        """
        gcode = self.compile_combined(jobs)
        
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(gcode)
        
        return file_path
    
    def compile_separate(self, jobs: List[LayerJob], output_dir: str,
                         base_filename: str, add_numeric_suffix: bool = False) -> List[str]:
        """
        Compile each enabled job into a separate G-code file.
        
        :param jobs: List of LayerJob objects
        :param output_dir: Directory to write files
        :param base_filename: Base filename (e.g., "output.gcode")
        :param add_numeric_suffix: If True, add numeric suffix to avoid overwrites
        :return: List of generated file paths
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # Split base filename into stem and extension
        base_stem, ext = os.path.splitext(base_filename)
        if not ext:
            ext = ".gcode"
        
        active_jobs = [j for j in jobs if j.enabled and j.curves]
        
        if not active_jobs:
            warnings.warn("No enabled jobs with curves to compile.")
            return []
        
        output_files = []
        
        for idx, job in enumerate(active_jobs):
            # Build safe filename
            safe_label = sanitize_filename(job.label)
            filename = f"{base_stem}_{idx + 1:02d}_{safe_label}{ext}"
            file_path = os.path.join(output_dir, filename)
            
            # Handle numeric suffix for collision avoidance
            if add_numeric_suffix:
                counter = 1
                original_path = file_path
                while os.path.exists(file_path):
                    file_path = os.path.join(
                        output_dir, 
                        f"{base_stem}_{idx + 1:02d}_{safe_label}_{counter}{ext}"
                    )
                    counter += 1
            
            # Compile single job to file
            self._compile_single_job_to_file(job, file_path)
            output_files.append(file_path)
        
        return output_files
    
    def _compile_single_job_to_file(self, job: LayerJob, file_path: str):
        """Compile a single job to a standalone G-code file."""
        compiler = self._build_job_compiler(job)
        
        # Add curves
        if job.curves:
            compiler.append_curves(job.curves)
        
        # Build full G-code with header/footer for this job
        gcode_lines = []
        
        # Header
        gcode_lines.append("G90;")
        gcode_lines.append(f"{'G21;' if self.unit == 'mm' else 'G20;'}")
        for cmd in self.custom_header:
            if cmd.strip():
                gcode_lines.append(_expand_escapes(cmd))
        
        # Body (with passes)
        if compiler.body:
            for pass_idx in range(job.passes):
                if pass_idx > 0:
                    gcode_lines.append(_expand_escapes(job.laser_off_command))
                    if job.pass_depth > 0:
                        temp_interface = _JobGcodeInterface(job)
                        # Set movement speed for Z move
                        temp_interface.set_movement_speed(job.travel_speed)
                        gcode_lines.append(temp_interface.set_relative_coordinates())
                        gcode_lines.append(temp_interface.linear_move(z=-job.pass_depth))
                        gcode_lines.append(temp_interface.set_absolute_coordinates())
                gcode_lines.extend(compiler.body)
            
            # Laser off after job
            gcode_lines.append(_expand_escapes(job.laser_off_command))
        else:
            warnings.warn(f"Job '{job.label}' produced empty body.")
        
        # Footer
        for cmd in self.custom_footer:
            if cmd.strip():
                gcode_lines.append(_expand_escapes(cmd))
        
        # Filter and write
        gcode_lines = [cmd for cmd in gcode_lines if cmd and cmd.strip()]
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(gcode_lines))


# Backward compatibility alias
MultiLayerGcodeCompiler = MultiLayerCompiler