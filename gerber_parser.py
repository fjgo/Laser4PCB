import re
import math
import os
from shapely.geometry import Polygon, MultiPolygon, LineString, Point
from shapely.ops import unary_union
from shapely.affinity import rotate as shapely_rotate, scale as shapely_scale, translate
from expression_evaluator import ExpressionEvaluator


def apply_transformations(shape, transform):
    """
    Aplica transformaciones a una forma Shapely.
    """
    if not shape:
        return shape
    if transform["mirror"] == "X":
        shape = shapely_scale(shape, xfact=-1.0, yfact=1.0, origin=(0, 0))
    elif transform["mirror"] == "Y":
        shape = shapely_scale(shape, xfact=1.0, yfact=-1.0, origin=(0, 0))
    elif transform["mirror"] == "XY":
        shape = shapely_scale(shape, xfact=-1.0, yfact=-1.0, origin=(0, 0))
    if transform["rotation"] != 0:
        shape = shapely_rotate(shape, transform["rotation"], origin=(0, 0))
    if transform["scale"] != 1.0:
        shape = shapely_scale(
            shape, xfact=transform["scale"], yfact=transform["scale"], origin=(0, 0)
        )
    return shape


class GerberParser:
    """
    Un parser de archivos Gerber X2 que convierte el contenido del archivo en una lista de primitivas geométricas,
    aplicando transformaciones y evaluando expresiones matemáticas de forma segura.
    Implementa arcos (G02/G03) y lee atributos de fichero X2.
    """

    def __init__(self):
        self.expr_eval = ExpressionEvaluator()

        # Estado de coordenadas y gráficos
        self.x, self.y = 0.0, 0.0
        self.units = "mm"
        self.format_x = (2, 6)
        self.format_y = (2, 6)

        # Estado de la máquina
        self.current_aperture_d_code = None
        self.plot_mode = "G01"
        self.in_region_mode = False
        self.last_operation_code = None
        self.quadrant_mode = "G75"

        # Diccionarios de definiciones
        self.apertures = {}
        self.aperture_macros = {}

        # Estado de la región
        self.region_contours = []
        self.current_contour = []

        # Estado de transformación
        self.transforms = {
            "polarity": "dark",
            "mirror": "N",
            "rotation": 0.0,
            "scale": 1.0,
        }

        # Primitivas finales con formas ya transformadas
        self.primitives = []

        # Atributos de fichero (Gerber X2)
        self.file_function = None
        self.filename = None
        self.guessed_layer = None
        self.file_polarity = "positive"

    def _guess_layer_from_filename(self, filename):
        """Intenta adivinar la función de la capa a partir del nombre del fichero."""
        # Mapeo de extensiones comunes a funciones de capa estándar
        ext_map = {
            ".gtl": "Copper,L1,Top",
            ".gbl": "Copper,L2,Bot",
            ".gts": "SolderMask,Top",
            ".gbs": "SolderMask,Bot",
            ".gto": "Legend,Top",
            ".gbo": "Legend,Bot",
            ".gml": "Mechanical,L1",  # O Profile
            ".gm1": "Mechanical,L1",
            ".gko": "KeepOut,All",
            ".drl": "Drill,Plated,NPTH",
            ".txt": "Drill,Plated,NPTH",
        }

        lower_filename = filename.lower()

        # Buscar por extensión
        for ext, layer_func in ext_map.items():
            if lower_filename.endswith(ext):
                return layer_func

        # Si no se encuentra por extensión, buscar por palabras clave en el nombre
        if "top" in lower_filename and "copper" in lower_filename:
            return "Copper,L1,Top"
        if "bottom" in lower_filename and "copper" in lower_filename:
            return "Copper,L2,Bot"
        if "top" in lower_filename and "mask" in lower_filename:
            return "SolderMask,Top"
        if "bottom" in lower_filename and "mask" in lower_filename:
            return "SolderMask,Bot"
        if "top" in lower_filename and (
            "silk" in lower_filename or "legend" in lower_filename
        ):
            return "Legend,Top"
        if "bottom" in lower_filename and (
            "silk" in lower_filename or "legend" in lower_filename
        ):
            return "Legend,Bot"
        if (
            "profile" in lower_filename
            or "outline" in lower_filename
            or "board" in lower_filename
        ):
            return "Profile,NP"

        return "Unknown"

    def _parse_coordinate(self, value_str, axis_format):
        if value_str is None:
            return None
        sign = -1 if value_str.startswith("-") else 1
        if value_str.startswith(("+", "-")):
            value_str = value_str[1:]
        num_integers, num_decimals = axis_format
        value_str = value_str.zfill(num_integers + num_decimals)
        integer_part = value_str[:-num_decimals]
        decimal_part = value_str[-num_decimals:]
        val = float(f"{integer_part}.{decimal_part}")
        return sign * val

    def _handle_format_spec(self, command):
        match = re.match(r"FSLAX(\d)(\d)Y(\d)(\d)", command)
        if match:
            self.format_x = (int(match.group(1)), int(match.group(2)))
            self.format_y = (int(match.group(3)), int(match.group(4)))

    def _handle_mode(self, command):
        if "MM" in command:
            self.units = "mm"
        elif "IN" in command:
            self.units = "in"

    def _handle_load_polarity(self, command):
        if "LPC" in command:
            self.transforms["polarity"] = "clear"
        elif "LPD" in command:
            self.transforms["polarity"] = "dark"

    def _handle_load_transform(self, command):
        if command.startswith("LM"):
            m = command[2:]
            if m in ["N", "X", "Y", "XY"]:
                self.transforms["mirror"] = m
        elif command.startswith("LR"):
            self.transforms["rotation"] = float(command[2:])
        elif command.startswith("LS"):
            self.transforms["scale"] = float(command[2:])

    def _handle_file_attribute(self, command):
        """Busca atributos de fichero como .FileFunction."""
        if command.startswith("TF.FileFunction,"):
            self.file_function = command.split(",", 1)[1]
        elif command.startswith("TF.FilePolarity,"):
            self.file_polarity = command.split(",", 1)[1].strip().lower()

    def get_effective_polarity(self, primitive_polarity):
        """Devuelve la polaridad efectiva según la polaridad global del archivo."""
        if self.file_polarity == "negative":
            return "dark" if primitive_polarity == "clear" else "clear"
        return primitive_polarity

    def _evaluate_expression(self, expr_str, variables):
        return self.expr_eval.evaluate(expr_str, variables)

    def _instantiate_macro(self, macro_name, ad_params):
        if macro_name not in self.aperture_macros:
            raise ValueError(f"Macro de apertura '{macro_name}' no definida.")
        macro_def = self.aperture_macros[macro_name]
        variables = {i + 1: p for i, p in enumerate(ad_params)}
        macro_geometries = []
        for item in macro_def:
            if item[0] == "var_def":
                var_num = int(item[1][1:])
                variables[var_num] = self._evaluate_expression(item[2], variables)
            elif item[0] == "primitive":
                code = int(item[1])
                params = [self._evaluate_expression(p, variables) for p in item[2]]
                # 7 (Thermal) no tiene exposure
                exposure = bool(params.pop(0)) if code != 7 else True
                primitive_geom = None
                if code == 0:
                    # Comentario, no genera geometría
                    continue
                elif code == 1:
                    # Circle: Exposure, Diameter, Center X, Center Y[, Rotation]
                    dia, cx, cy = params[0], params[1], params[2]
                    rot = params[3] if len(params) > 3 else 0.0
                    primitive_geom = Point(cx, cy).buffer(dia / 2.0)
                    if rot != 0:
                        primitive_geom = shapely_rotate(
                            primitive_geom, rot, origin=(cx, cy)
                        )
                elif (
                    code == 20
                ):
                    # Vector Line: Exposure, Width, Start X, Start Y, End X, End Y, Rotation
                    width, x1, y1, x2, y2, rot = params
                    line = LineString([(x1, y1), (x2, y2)])
                    primitive_geom = line.buffer(width / 2.0, cap_style=2)
                    if rot != 0:
                        primitive_geom = shapely_rotate(
                            primitive_geom, rot, origin=(0, 0)
                        )
                elif (
                    code == 21
                ):
                    # Center Line: Exposure, Width, Height, Center X, Center Y, Rotation
                    width, height, cx, cy, rot = params
                    rect = Polygon(
                        [
                            (-width / 2, -height / 2),
                            (width / 2, -height / 2),
                            (width / 2, height / 2),
                            (-width / 2, height / 2),
                        ]
                    )
                    rect = translate(rect, cx, cy)
                    if rot != 0:
                        rect = shapely_rotate(rect, rot, origin=(cx, cy))
                    primitive_geom = rect
                elif (
                    code == 4
                ):
                    # Outline: Exposure, #vertices, x1, y1, ..., xn, yn, Rotation
                    n_vertices = int(params[0])
                    vertices = []
                    for i in range(n_vertices):
                        x = params[1 + 2 * i]
                        y = params[2 + 2 * i]
                        vertices.append((x, y))
                    rot = params[-1]
                    poly = Polygon(vertices)
                    if rot != 0:
                        poly = shapely_rotate(poly, rot, origin=(0, 0))
                    primitive_geom = poly
                elif (
                    code == 5
                ):
                    # Polygon: Exposure, #vertices, Center X, Center Y, Diameter, Rotation
                    n_vertices = int(params[0])
                    cx, cy, dia, rot = params[1], params[2], params[3], params[4]
                    angle_step = 2 * math.pi / n_vertices
                    points = [
                        (
                            cx
                            + (dia / 2.0)
                            * math.cos(rot * math.pi / 180 + i * angle_step),
                            cy
                            + (dia / 2.0)
                            * math.sin(rot * math.pi / 180 + i * angle_step),
                        )
                        for i in range(n_vertices)
                    ]
                    primitive_geom = Polygon(points)
                elif (
                    code == 7
                ):
                    # Thermal: Center X, Center Y, Outer diameter, Inner diameter, Gap, Rotation
                    cx, cy, outer_dia, inner_dia, gap, rot = params
                    outer = Point(cx, cy).buffer(outer_dia / 2.0)
                    inner = Point(cx, cy).buffer(inner_dia / 2.0)
                    thermal = outer.difference(inner)
                    # Gaps: crear 4 rectángulos y restarlos
                    for i in range(4):
                        angle = rot + i * 90
                        rad = math.radians(angle)
                        x1 = cx + (inner_dia / 2) * math.cos(rad)
                        y1 = cy + (inner_dia / 2) * math.sin(rad)
                        x2 = cx + (outer_dia / 2) * math.cos(rad)
                        y2 = cy + (outer_dia / 2) * math.sin(rad)
                        gap_rect = Polygon(
                            [
                                (
                                    x1 + (gap / 2) * math.cos(rad + math.pi / 2),
                                    y1 + (gap / 2) * math.sin(rad + math.pi / 2),
                                ),
                                (
                                    x1 - (gap / 2) * math.cos(rad + math.pi / 2),
                                    y1 - (gap / 2) * math.sin(rad + math.pi / 2),
                                ),
                                (
                                    x2 - (gap / 2) * math.cos(rad + math.pi / 2),
                                    y2 - (gap / 2) * math.sin(rad + math.pi / 2),
                                ),
                                (
                                    x2 + (gap / 2) * math.cos(rad + math.pi / 2),
                                    y2 + (gap / 2) * math.sin(rad + math.pi / 2),
                                ),
                            ]
                        )
                        thermal = thermal.difference(gap_rect)
                    primitive_geom = thermal

                if primitive_geom:
                    macro_geometries.append(
                        {"shape": primitive_geom, "exposure": exposure}
                    )
        dark_shapes = [g["shape"] for g in macro_geometries if g["exposure"]]
        clear_shapes = [g["shape"] for g in macro_geometries if not g["exposure"]]
        final_geom = MultiPolygon()
        if dark_shapes:
            final_geom = unary_union(dark_shapes)
        if clear_shapes:
            final_geom = final_geom.difference(unary_union(clear_shapes))
        return final_geom

    def _handle_aperture_macro(self, command_block):
        lines = [line.strip() for line in command_block.split("*") if line.strip()]
        macro_name = lines.pop(0)
        macro_definition = []
        for line in lines:
            if "=" in line:
                var, expr = line.split("=", 1)
                macro_definition.append(("var_def", var.strip(), expr.strip()))
            else:
                # Eliminar comentarios
                if not line.startswith("0"):
                    parts = line.split(",")
                    macro_definition.append(
                        ("primitive", parts[0].strip(), [p.strip() for p in parts[1:]])
                    )
        self.aperture_macros[macro_name] = macro_definition

    def _handle_aperture_define(self, command):
        match = re.match(r"ADD(\d+)(.*)", command)
        if not match:
            return
        d_code, params_str = int(match.group(1)), match.group(2)

        if "," in params_str:
            template_name, params_list_str = params_str.split(",", 1)
            params_list = re.split(r"[xX]", params_list_str)
        else:
            template_name = params_str
            params_list = []

        params = [float(p) for p in params_list if p]
        aperture_info = {"shape": None, "type": template_name, "params": params}

        try:
            if template_name == "C":
                dia = params[0]
                shape = Point(0, 0).buffer(dia / 2.0)
                if len(params) > 1:
                    shape = shape.difference(Point(0, 0).buffer(params[1] / 2.0))
                aperture_info.update({"shape": shape, "diameter": dia})
            elif template_name == "R":
                w, h = params[0], params[1]
                shape = Polygon(
                    [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
                )
                if len(params) > 2:
                    shape = shape.difference(Point(0, 0).buffer(params[2] / 2.0))
                aperture_info["shape"] = shape
            elif template_name == "O":
                w, h = params[0], params[1]
                if w > h:
                    line = LineString([(-(w - h) / 2, 0), ((w - h) / 2, 0)])
                    shape = line.buffer(h / 2, cap_style=1)
                else:
                    line = LineString([(0, -(h - w) / 2), (0, (h - w) / 2)])
                    shape = line.buffer(w / 2, cap_style=1)
                if len(params) > 2:
                    shape = shape.difference(Point(0, 0).buffer(params[2] / 2.0))
                aperture_info["shape"] = shape
            elif template_name == "P":
                dia, n_vertices, rot = (
                    params[0],
                    int(params[1]),
                    params[2] if len(params) > 2 else 0.0,
                )
                angle_step = 360.0 / n_vertices
                points = [
                    (
                        (dia / 2) * math.cos(math.radians(rot + i * angle_step)),
                        (dia / 2) * math.sin(math.radians(rot + i * angle_step)),
                    )
                    for i in range(n_vertices)
                ]
                shape = Polygon(points)
                if len(params) > 3:
                    shape = shape.difference(Point(0, 0).buffer(params[3] / 2.0))
                aperture_info["shape"] = shape
            else:
                shape = self._instantiate_macro(template_name, params)
                aperture_info.update({"shape": shape, "type": "MACRO"})
        except Exception as e:
            print(f"ERROR: Parámetros incorrectos para apertura D{d_code}: {e}")
            return

        if aperture_info["shape"]:
            self.apertures[d_code] = aperture_info

    def _create_arc_path(self, start, end, center, clockwise):
        radius_start = math.dist(start, center)
        radius_end = math.dist(end, center)

        if not math.isclose(radius_start, radius_end, rel_tol=1e-4):
            print(f"ERROR: Radios de arco inconsistentes. Tratando como línea.")
            return LineString([start, end])

        radius = radius_start
        if radius == 0:
            return LineString([start, end])

        start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
        end_angle = math.atan2(end[1] - center[1], end[0] - center[0])

        if clockwise:
            if end_angle > start_angle:
                end_angle -= 2 * math.pi
        else:
            if end_angle < start_angle:
                end_angle += 2 * math.pi

        if math.isclose(start[0], end[0]) and math.isclose(start[1], end[1]):
            end_angle = start_angle + (-2 * math.pi if clockwise else 2 * math.pi)

        total_angle = abs(end_angle - start_angle)
        num_segments = max(2, int(math.ceil(total_angle * radius / 0.05)))

        points = [start]
        for i in range(1, num_segments):
            angle = start_angle + i * (end_angle - start_angle) / num_segments
            points.append(
                (
                    center[0] + radius * math.cos(angle),
                    center[1] + radius * math.sin(angle),
                )
            )
        points.append(end)

        return LineString(points)

    def _execute_operation(self, command):
        op_match = re.search(r"D(0[1-3])$", command)
        op_code = op_match.group(1) if op_match else self.last_operation_code
        if not op_code:
            return
        if op_match:
            self.last_operation_code = op_code

        x_match = re.search(r"X(-?\d+)", command)
        y_match = re.search(r"Y(-?\d+)", command)
        i_match = re.search(r"I(-?\d+)", command)
        j_match = re.search(r"J(-?\d+)", command)

        new_x = self._parse_coordinate(
            x_match.group(1) if x_match else None, self.format_x
        )
        if new_x is None:
            new_x = self.x
        new_y = self._parse_coordinate(
            y_match.group(1) if y_match else None, self.format_y
        )
        if new_y is None:
            new_y = self.y

        if self.in_region_mode:
            if op_code == "01":
                if not self.current_contour:
                    self.current_contour.append(("move", (self.x, self.y)))
                if (
                    self.plot_mode in ["G02", "G03"]
                    and i_match
                    and j_match
                    and self.quadrant_mode == "G75"
                ):
                    i = self._parse_coordinate(i_match.group(1), self.format_x)
                    j = self._parse_coordinate(j_match.group(1), self.format_y)
                    self.current_contour.append(
                        (
                            "arc",
                            (new_x, new_y),
                            (self.x + i, self.y + j),
                            self.plot_mode == "G02",
                        )
                    )
                else:
                    self.current_contour.append(("line", (new_x, new_y)))
            elif op_code == "02":
                if self.current_contour:
                    self.region_contours.append(self.current_contour)
                self.current_contour = [("move", (new_x, new_y))]
        else:
            if op_code == "01":
                # Draw/Track
                start_point = (self.x, self.y)
                end_point = (new_x, new_y)

                aperture_def = self.apertures.get(self.current_aperture_d_code)
                if not aperture_def:
                    self.x, self.y = new_x, new_y
                    return

                width = aperture_def.get("diameter", 0)
                if width <= 0:
                    self.x, self.y = new_x, new_y
                    return

                path = None
                if (
                    self.plot_mode in ["G02", "G03"]
                    and i_match
                    and j_match
                    and self.quadrant_mode == "G75"
                ):
                    i = self._parse_coordinate(i_match.group(1), self.format_x)
                    j = self._parse_coordinate(j_match.group(1), self.format_y)
                    center = (self.x + i, self.y + j)
                    path = self._create_arc_path(
                        start_point, end_point, center, self.plot_mode == "G02"
                    )
                else:
                    path = LineString([start_point, end_point])

                if path:
                    buffered_path = path.buffer(width / 2.0, cap_style=1)
                    transformed_path = apply_transformations(
                        buffered_path, self.transforms
                    )
                    polarity = self.transforms["polarity"]
                    self.primitives.append(
                        {
                            "type": "track",
                            "shape": transformed_path,
                            "polarity": polarity,
                            "effective_polarity": self.get_effective_polarity(polarity),
                        }
                    )

            elif op_code == "03":
                # Flash
                aperture_def = self.apertures.get(self.current_aperture_d_code)
                if aperture_def and aperture_def["shape"]:
                    translated_shape = translate(aperture_def["shape"], new_x, new_y)
                    transformed_shape = apply_transformations(
                        translated_shape, self.transforms
                    )
                    polarity = self.transforms["polarity"]
                    self.primitives.append(
                        {
                            "type": "flash",
                            "shape": transformed_shape,
                            "polarity": polarity,
                            "effective_polarity": self.get_effective_polarity(polarity),
                        }
                    )

        self.x, self.y = new_x, new_y

    def parse(self, gerber_content=None, filepath=None, encoding="utf-8"):
        """
        Analiza el contenido de un fichero Gerber.
        Puede recibir el contenido como un string (gerber_content)
        o la ruta a un fichero (filepath).
        """
        if filepath:
            self.filename = os.path.basename(filepath)
            try:
                with open(filepath, "r", encoding=encoding) as f:
                    gerber_content = f.read()
                # Adivinar la capa solo si se proporciona un fichero
                self.guessed_layer = self._guess_layer_from_filename(self.filename)
            except FileNotFoundError:
                raise
            except Exception as e:
                raise IOError(f"No se pudo leer el fichero: {filepath}") from e
        elif gerber_content is None:
            raise ValueError("Se debe proporcionar 'gerber_content' o 'filepath'.")

        gerber_content = gerber_content.replace("\n", "").replace("\r", "")
        command_re = re.compile(r"%(?P<ext>.*?)%|(?P<cmd>[^\*%]+)\*")
        for match in command_re.finditer(gerber_content):
            ext_cmd = match.group("ext")
            cmd = match.group("cmd")

            if ext_cmd is not None:
                if ext_cmd.startswith("AM"):
                    self._handle_aperture_macro(ext_cmd[2:])
                else:
                    for sub_cmd in ext_cmd.split("*"):
                        sub_cmd = sub_cmd.strip()
                        if not sub_cmd:
                            continue
                        if sub_cmd.startswith("TF"):
                            self._handle_file_attribute(sub_cmd)
                        elif sub_cmd.startswith("FS"):
                            self._handle_format_spec(sub_cmd)
                        elif sub_cmd.startswith("MO"):
                            self._handle_mode(sub_cmd)
                        elif sub_cmd.startswith("AD"):
                            self._handle_aperture_define(sub_cmd)
                        elif sub_cmd.startswith("LP"):
                            self._handle_load_polarity(sub_cmd)
                        elif sub_cmd.startswith(("LM", "LR", "LS")):
                            self._handle_load_transform(sub_cmd)

            if cmd is not None:
                cmd = cmd.strip()
                if cmd.startswith("G"):
                    if cmd in ["G01", "G02", "G03"]:
                        self.plot_mode = cmd
                    elif cmd in ["G74", "G75"]:
                        self.quadrant_mode = cmd
                    elif cmd == "G36":
                        (
                            self.in_region_mode,
                            self.region_contours,
                            self.current_contour,
                        ) = (True, [], [])
                    elif cmd == "G37":
                        self.in_region_mode = False
                        if self.current_contour:
                            self.region_contours.append(self.current_contour)
                        self.current_contour = []
                        all_regions = []
                        for contour in self.region_contours:
                            points = []
                            for action in contour:
                                if action[0] in ("move", "line", "arc"):
                                    points.append(action[1])
                            if len(points) < 3:
                                # No podemos formar un polígono con menos de 3 puntos
                                continue
                            try:
                                poly = Polygon(points)
                                if not poly.is_valid:
                                    # Intentamos sanear el polígono
                                    poly = poly.buffer(0)
                                    if not poly.is_valid:
                                        continue
                                all_regions.append(poly)
                            except Exception as e:
                                print(f"Error creando región: {e}")
                        if all_regions:
                            combined_dark = unary_union(all_regions)
                            transformed_dark = apply_transformations(
                                combined_dark, self.transforms
                            )
                            polarity = self.transforms["polarity"]
                            self.primitives.append(
                                {
                                    "type": "region",
                                    "shape": transformed_dark,
                                    "contours": self.region_contours,
                                    "polarity": polarity,
                                    "effective_polarity": self.get_effective_polarity(
                                        polarity
                                    ),
                                }
                            )

                        self.region_contours = []
                    elif cmd.startswith("G04"):
                        # Comprobar si es un comentario con atributo embebido (fuera de norma pero común)
                        if cmd.startswith("G04 #@!"):
                            # Extraer el comando real que está "escondido"
                            embedded_cmd = cmd[len("G04 #@!") :].strip()
                            if embedded_cmd.startswith("TF"):
                                self._handle_file_attribute(embedded_cmd)
                        continue
                elif cmd.startswith("D") and cmd[1:].isdigit():
                    d_code = int(cmd[1:])
                    if d_code >= 10:
                        self.current_aperture_d_code, self.last_operation_code = (
                            d_code,
                            None,
                        )
                    else:
                        self._execute_operation(cmd)
                elif cmd.startswith("M02"):
                    break
                else:
                    self._execute_operation(cmd)

    def get_primitives(self):
        return self.primitives

    def get_file_function(self):
        return self.file_function

    def get_filename(self):
        """Devuelve el nombre base del fichero parseado, si se usó un filepath."""
        return self.filename

    def get_guessed_layer(self):
        """Devuelve la función de capa adivinada a partir del nombre del fichero."""
        return self.guessed_layer
