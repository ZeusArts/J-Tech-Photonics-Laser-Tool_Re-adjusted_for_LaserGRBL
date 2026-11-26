import os
import warnings
from typing import List

from lxml import etree
from xml.etree import ElementTree as xml_tree
from inkex import EffectExtension, Boolean

from svg_to_gcode.svg_parser import parse_root, parse_layers, Transformation, debug_methods
from svg_to_gcode.geometry import LineSegmentChain, Vector
from svg_to_gcode.compiler import Compiler, interfaces, MultiLayerCompiler, LayerJob
from gui import (
    show_layer_dialog,
    save_config_to_svg,
    load_config_from_svg,
    build_jobs_from_dialog_result,
)
from svg_to_gcode import TOLERANCES

svg_name_space = "http://www.w3.org/2000/svg"
inkscape_name_space = "http://www.inkscape.org/namespaces/inkscape"
sodipodi_name_space = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"

inx_filename = "laser.inx"


def generate_custom_interface(laser_off_command, laser_power_command):
    """Wrapper function for generating a Gcode interface with a custom laser power command"""

    class CustomInterface(interfaces.Gcode):
        """A Gcode interface with a custom laser power command"""

        def __init__(self):
            super().__init__()

        def laser_off(self):
            return f"{laser_off_command}".replace(r'\n', '\n')

        def set_laser_power(self, _):
            return f"{laser_power_command}".replace(r'\n', '\n')

    return CustomInterface


# Color palette for multi-layer debug traces
DEBUG_LAYER_COLORS = [
    "#0066ff",  # Blue
    "#ff0000",  # Red
    "#00aa00",  # Green
    "#ff8800",  # Orange
    "#9900cc",  # Purple
    "#00aaaa",  # Cyan
]


class GcodeExtension(EffectExtension):
    """Inkscape Effect Extension."""

    def __init__(self):
        EffectExtension.__init__(self)

    def effect(self):
        """Takes the SVG from Inkscape, generates gcode, returns the SVG after adding debug lines."""

        root = self.document.getroot()

        # Change svg_to_gcode's approximation tolerance
        TOLERANCES["approximation"] = float(self.options.approximation_tolerance.replace(',', '.'))

        # Load header and footer files
        header = []
        if self.options.header_path is not None:
            if os.path.isfile(self.options.header_path):
                with open(self.options.header_path, 'r') as header_file:
                    header = header_file.read().splitlines()
            elif self.options.header_path != os.getcwd():  # The Inkscape file selector defaults to the working directory
                self.debug(f"Header file does not exist at {self.options.header_path}")
                exit(2)

        footer = []
        if self.options.footer_path is not None:
            if os.path.isfile(self.options.footer_path):
                with open(self.options.footer_path, 'r') as footer_file:
                    footer = footer_file.read().splitlines()
            elif self.options.footer_path != os.getcwd():
                self.debug(f"Footer file does not exist at {self.options.footer_path}")
                exit(2)

        # Unit conversion
        uu_per_unit = self.svg.unittouu(f"1{self.options.unit}")
        unit_per_uu = 1.0 / uu_per_unit

        # Build base transformation (offset, scaling, machine origin, unit conversion)
        transformation = Transformation()

        transformation.add_translation(self.options.horizontal_offset, self.options.vertical_offset)
        transformation.add_scale(self.options.scaling_factor)

        if self.options.machine_origin == "center":
            transformation.add_translation(-self.options.bed_width / 2, self.options.bed_height / 2)
        elif self.options.machine_origin == "top-left":
            transformation.add_translation(0, self.options.bed_height)

        transformation.add_scale(unit_per_uu)

        # Check if multi-layer GUI mode is enabled
        use_gui = getattr(self.options, "use_layer_gui", True)

        if use_gui:
            # Multi-layer GUI mode
            # Parse layers first (without GUI, we still need to parse to get layer info)
            self.clear_debug()
            layers = parse_layers(
                root,
                transform_origin=not self.options.invert_y_axis,
                root_transformation=transformation,
                canvas_height=self.options.bed_height,
                order="top_to_bottom",
            )

            # Load saved config from SVG
            saved_config = load_config_from_svg(root)

            # Prepare defaults for GUI
            defaults = {
                "travel_speed": self.options.travel_speed,
                "cutting_speed": self.options.cutting_speed,
                "passes": self.options.passes,
                "pass_depth": self.options.pass_depth,
                "laser_mode": "M3",
                "laser_power": 255,
                "laser_off_command": self.options.tool_off_command,
                "laser_power_command": self.options.tool_power_command,
                "dwell_time": self.options.dwell_time,
                "unit": self.options.unit,
            }

            # Show the layer configuration dialog
            result = show_layer_dialog(
                parent=None,  # Inkscape doesn't provide a Tk parent easily
                layers=layers,
                defaults=defaults,
                saved_config=saved_config,
                output_dir=self.options.directory,
                base_filename=self.options.filename,
                add_numeric_suffix=self.options.filename_suffix,
                unit=self.options.unit,
                bed_width=self.options.bed_width,
                bed_height=self.options.bed_height,
            )

            if not result.confirmed:
                # User cancelled - return without generating G-code or debug layers
                return self.document

            # Save config to SVG for next time
            save_config_to_svg(root, result.config_dict)

            # Validate output directory now (after GUI confirmation)
            try:
                assert os.path.isdir(self.options.directory)
            except:
                self.debug(f"{self.options.directory} is not a directory")
                exit(2)

            # Build LayerJob objects from dialog result
            jobs = build_jobs_from_dialog_result(result, layers)

            if not jobs:
                warnings.warn("No enabled layers with curves to compile.")
                return self.document

            # Determine output path
            if self.options.filename:
                filename = self.options.filename
                if '.' not in filename:
                    filename += ".gcode"
            elif self.document_path():
                filename, extension = self.document_path().split('.')
                filename = filename.split('/')[-1] + '.gcode'
            else:
                filename = "untitled.gcode"

            output_path = os.path.join(self.options.directory, filename)

            if self.options.filename_suffix:
                filename, extension = output_path.split('.')
                n = 1
                while os.path.isfile(output_path):
                    output_path = filename + str(n) + '.' + extension
                    n += 1

            # Compile using MultiLayerCompiler
            compiler = MultiLayerCompiler(
                unit=self.options.unit,
                custom_header=header,
                custom_footer=footer,
            )

            # Compile separate G-code file per enabled layer
            compiler.compile_separate(
                jobs,
                self.options.directory,
                filename,
                add_numeric_suffix=self.options.filename_suffix,
            )

            # Draw debug layers
            if self.options.draw_debug:
                self.draw_debug_traces_multilayer(jobs)
                self.draw_unit_reference()
                self.select_non_debug_layer()

        else:
            # Legacy single-settings mode (backward compatibility)
            # Validate output directory
            try:
                assert os.path.isdir(self.options.directory)
            except:
                self.debug(f"{self.options.directory} is not a directory")
                exit(2)

            # Construct output path
            if self.options.filename:
                filename = self.options.filename
                if '.' not in filename:
                    filename += ".gcode"
            elif self.document_path():
                filename, extension = self.document_path().split('.')
                filename = filename.split('/')[-1] + '.gcode'
            else:
                filename = "untitled.gcode"

            output_path = os.path.join(self.options.directory, filename)

            if self.options.filename_suffix:
                filename, extension = output_path.split('.')
                n = 1
                while os.path.isfile(output_path):
                    output_path = filename + str(n) + '.' + extension
                    n += 1

            # Customize header/footer
            custom_interface = generate_custom_interface(self.options.tool_off_command, self.options.tool_power_command)
            interface_instance = custom_interface()

            if self.options.do_laser_off_start:
                header.append(interface_instance.laser_off())
            if self.options.do_laser_off_end:
                footer.append(interface_instance.laser_off())

            header.append(interface_instance.set_movement_speed(self.options.travel_speed))
            if self.options.do_z_axis_start:
                header.append(interface_instance.linear_move(z=self.options.z_axis_start))
            if self.options.move_to_origin_end:
                footer.append(interface_instance.linear_move(x=0, y=0))

            # Generate gcode
            gcode_compiler = Compiler(custom_interface, self.options.travel_speed, self.options.cutting_speed,
                                      self.options.pass_depth, dwell_time=self.options.dwell_time, custom_header=header,
                                      custom_footer=footer, unit=self.options.unit)

            self.clear_debug()
            curves = parse_root(root, transform_origin=not self.options.invert_y_axis, root_transformation=transformation,
                                canvas_height=self.options.bed_height)

            gcode_compiler.append_curves(curves)
            gcode_compiler.compile_to_file(output_path, passes=self.options.passes)

            # Draw debug lines
            if self.options.draw_debug:
                self.draw_debug_traces(curves)
                self.draw_unit_reference()
                self.select_non_debug_layer()

        return self.document

    def draw_debug_traces(self, curves):
        """Traces arrows over all parsed paths"""

        root = self.document.getroot()
        origin = self.options.machine_origin
        bed_width = self.options.bed_width
        bed_height = self.options.bed_height
        uu_per_unit = self.svg.unittouu(f"1{self.options.unit}")
        stroke_width_uu = self.svg.unittouu(f"{self.options.debug_line_width}px")

        group = etree.Element("{%s}g" % svg_name_space)
        group.set("id", "debug_traces")
        group.set("{%s}groupmode" % inkscape_name_space, "layer")
        group.set("{%s}label" % inkscape_name_space, "debug traces")

        group.append(
            etree.fromstring(xml_tree.tostring(debug_methods.arrow_defs(arrow_scale=self.options.debug_arrow_scale))))

        for curve in curves:
            approximation = LineSegmentChain.line_segment_approximation(curve)

            change_origin = Transformation()
            change_origin.add_scale(uu_per_unit)

            if not self.options.invert_y_axis:
                change_origin.add_scale(1, -1)
                change_origin.add_translation(0, -bed_height)

            if origin == "center":
                change_origin.add_translation(bed_width / 2, bed_height / 2)
            elif origin == "top-left":
                # For top-left origin with invert_y_axis=False, we need to translate Y by bed_height
                # The SVG Y=0 is at top, G-code Y=0 is at top for top-left origin
                # So no additional translation needed here beyond the Y flip
                pass

            path_string = xml_tree.tostring(
                debug_methods.to_svg_path(approximation, color="red", opacity="0.5",
                                          stroke_width=str(stroke_width_uu),
                                          transformation=change_origin, draw_arrows=True)
            )

            group.append(etree.fromstring(path_string))

        root.append(group)

    def draw_debug_traces_multilayer(self, jobs: List[LayerJob]):
        """Traces arrows over all parsed paths with per-layer colors and order labels"""

        root = self.document.getroot()
        origin = self.options.machine_origin
        bed_width = self.options.bed_width
        bed_height = self.options.bed_height
        uu_per_unit = self.svg.unittouu(f"1{self.options.unit}")
        px_to_uu = self.svg.unittouu("1px")
        stroke_width_uu = self.svg.unittouu(f"{self.options.debug_line_width}px")

        group = etree.Element("{%s}g" % svg_name_space)
        group.set("id", "debug_traces")
        group.set("{%s}groupmode" % inkscape_name_space, "layer")
        group.set("{%s}label" % inkscape_name_space, "debug traces")

        group.append(
            etree.fromstring(xml_tree.tostring(debug_methods.arrow_defs(arrow_scale=self.options.debug_arrow_scale))))

        for job_idx, job in enumerate(jobs):
            color = DEBUG_LAYER_COLORS[job_idx % len(DEBUG_LAYER_COLORS)]

            for curve in job.curves:
                approximation = LineSegmentChain.line_segment_approximation(curve)

                change_origin = Transformation()
                change_origin.add_scale(uu_per_unit)

                if not self.options.invert_y_axis:
                    change_origin.add_scale(1, -1)
                    change_origin.add_translation(0, -bed_height)

                if origin == "center":
                    change_origin.add_translation(bed_width / 2, bed_height / 2)
                elif origin == "top-left":
                    # For top-left origin with invert_y_axis=False, no additional translation
                    pass

                path_string = xml_tree.tostring(
                    debug_methods.to_svg_path(approximation, color=color, opacity="0.5",
                                              stroke_width=str(stroke_width_uu),
                                              transformation=change_origin, draw_arrows=True)
                )

                group.append(etree.fromstring(path_string))

            # Draw order label at the start of the first curve
            if job.curves:
                first_curve = job.curves[0]
                start_point = first_curve.point(0)

                # Transform to SVG coordinates
                label_transform = Transformation()
                label_transform.add_scale(uu_per_unit)

                if not self.options.invert_y_axis:
                    label_transform.add_scale(1, -1)
                    label_transform.add_translation(0, -bed_height)

                if origin == "center":
                    label_transform.add_translation(bed_width / 2, bed_height / 2)
                elif origin == "top-left":
                    pass

                svg_point = label_transform.apply_affine_transformation(start_point)

                # Create label
                label_group = etree.Element("{%s}g" % svg_name_space)

                # Circle background
                circle = etree.Element("{%s}circle" % svg_name_space)
                circle.set("cx", str(svg_point.x))
                circle.set("cy", str(svg_point.y))
                circle.set("r", str(10 * px_to_uu))
                circle.set("fill", "white")
                circle.set("stroke", "black")
                circle.set("stroke-width", str(2 * px_to_uu))
                label_group.append(circle)

                # Text
                text = etree.Element("{%s}text" % svg_name_space)
                text.set("x", str(svg_point.x))
                text.set("y", str(svg_point.y + 4 * px_to_uu))
                text.set("font-size", str(8 * px_to_uu))
                text.set("text-anchor", "middle")
                text.set("dominant-baseline", "middle")
                text.set("fill", "black")
                text.text = f"#{job_idx + 1}"
                label_group.append(text)

                group.append(label_group)

        root.append(group)

    def draw_unit_reference(self):
        """Draws reference points to mark the bed's four corners"""
        root = self.document.getroot()
        unit = self.options.unit
        origin = self.options.machine_origin
        bed_width = self.options.bed_width
        bed_height = self.options.bed_height
        uu_per_unit = self.svg.unittouu(f"1{unit}")
        px_to_uu = self.svg.unittouu("1px")
        svg_bed_width = bed_width * uu_per_unit
        svg_bed_height = bed_height * uu_per_unit

        group = etree.Element("{%s}g" % svg_name_space)
        group.set("id", "debug_references")
        group.set("{%s}groupmode" % inkscape_name_space, "layer")
        group.set("{%s}label" % inkscape_name_space, "debug reference points")

        reference_points_svg = [(0, 0), (0, svg_bed_height), (svg_bed_width, 0), (svg_bed_width, svg_bed_height)]
        reference_points_gcode = {
            "bottom-left": [(0, bed_height), (0, 0), (bed_width, bed_height), (bed_width, 0)],
            "top-left": [(0, 0), (0, bed_height), (bed_width, 0), (bed_width, bed_height)],
            "center": [(-bed_width / 2, bed_height / 2), (-bed_width / 2, -bed_height / 2),
                       (bed_width / 2, bed_height / 2),
                       (bed_width / 2, -bed_height / 2)]
        }[origin]
        for i, (x, y) in enumerate(reference_points_svg):
            reference_point = etree.Element("{%s}g" % svg_name_space)

            stroke_width = 2 * px_to_uu
            size = 7 * px_to_uu

            x_direction = -1 if x > 0 else 1
            plus_sign = etree.Element("{%s}g" % svg_name_space)
            horizontal = etree.Element("{%s}line" % svg_name_space)
            horizontal.set("x1", str(x - x_direction * stroke_width / 2))
            horizontal.set("y1", str(y))
            horizontal.set("x2", str(x + x_direction * size))
            horizontal.set("y2", str(y))
            horizontal.set("style", f"stroke:black;stroke-width:{stroke_width}")
            plus_sign.append(horizontal)

            y_direction = -1 if y > 0 else 1
            vertical = etree.Element("{%s}line" % svg_name_space)
            vertical.set("x1", str(x))
            vertical.set("y1", str(y + stroke_width / 2))
            vertical.set("x2", str(x))
            vertical.set("y2", str(y + y_direction * size))
            vertical.set("style", f"stroke:black;stroke-width:{stroke_width}")
            plus_sign.append(vertical)

            reference_point.append(plus_sign)

            text_box = etree.Element("{%s}text" % svg_name_space)
            text_box.set("x", str(x - 28 * px_to_uu))
            text_box.set("y", str(y - (y <= 0) * 6 * px_to_uu + (y > 0) * 9 * px_to_uu))
            text_box.set("font-size", str(6 * px_to_uu))
            text_box.text = f"{reference_points_gcode[i][0]}{unit}, {reference_points_gcode[i][1]}{unit}"
            reference_point.append(text_box)

            group.append(reference_point)

        root.append(group)

    def select_non_debug_layer(self):
        """
        Select content_layer and create one if it doesn't exist. This helps stop the user from accidentally placing new
        objects in debug layers.
        """

        root = self.document.getroot()

        unique_id = "layer89324"
        content_layer = root.find("{%s}g[@id='%s']" % (svg_name_space, unique_id))

        if content_layer is None:
            content_layer = etree.Element("{%s}g" % svg_name_space)
            content_layer.set("id", unique_id)
            content_layer.set("{%s}groupmode" % inkscape_name_space, "layer")
            content_layer.set("{%s}label" % inkscape_name_space, "content layer")

        sodipodi = root.find("{%s}namedview" % sodipodi_name_space)
        if sodipodi is not None:
            sodipodi.set("{%s}current-layer" % inkscape_name_space, unique_id)

        root.append(content_layer)

    def clear_debug(self):
        """Removes debug groups. Used before parsing paths for gcode."""
        root = self.document.getroot()

        debug_traces = root.find("{%s}g[@id='debug_traces']" % svg_name_space)
        debug_references = root.find("{%s}g[@id='debug_references']" % svg_name_space)

        if debug_traces is not None:
            root.remove(debug_traces)

        if debug_references is not None:
            root.remove(debug_references)

    def add_arguments(self, arg_parser):
        """Tell inkscape what arguments to stick in self.options (behind the hood it's more complicated, see docs)"""
        arguments = self.read_arguments()

        for arg in arguments:
            arg_parser.add_argument("--" + arg["name"], type=arg["type"], dest=arg["name"])

    @staticmethod
    def read_arguments():
        """
        This method reads arguments off of the inx file so you don't have to explicitly declare them in self.add_arguments()
        """
        root = etree.parse(inx_filename).getroot()

        arguments = []  # [{name, type, ...}]
        namespace = "http://www.inkscape.org/namespace/inkscape/extension"
        for arg in root.iter("{%s}param" % namespace):

            name = arg.attrib["name"]

            arg_type = arg.attrib["type"]

            if arg_type in ["description", "notebook"]:
                continue

            types = {"int": int, "float": float, "bool": Boolean, "string": str, "optiongroup": str, "path": str}

            arguments.append({"name": name, "type": types[arg_type]})

        if next(root.iter("{%s}page" % namespace)) is not None:
            arguments.append({"name": "tabs", "type": str})

        return arguments


if __name__ == '__main__':
    effect = GcodeExtension()
    effect.run()
