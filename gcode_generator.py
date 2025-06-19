import re
from shapely.geometry import Polygon, MultiPolygon, LineString
from shapely.affinity import translate
from vector_canvas import DEFAULT_GRAPHIC_INFO


def generate_gcode(geometry, config, app_name=""):
    # config es el configparser de la aplicación, extraemos de eĺ los datos que nos interesan
    feed_rate = config["Engraver"].get("feed_rate")
    fast_move_rate = config["Engraver"].get("fast_move_rate", 6000)
    laser_power = config["Engraver"].get("laser_power", 1000)
    laser_on_cmd = config["Engraver"].get("laser_on_cmd", "M3")
    laser_off_cmd = config["Engraver"].get("laser_off_cmd", "M5")
    trace_outline = config["GCode"].get("trace_outline", True)
    fill_inner = config["GCode"].get("fill_inner", True)
    offset_distance = config["GCode"].get("offset_distance", 0.0)
    fill_spacing = config["GCode"].get("fill_spacing", 0.1)

    gcode = []
    full_laser_on_cmd = f"{laser_on_cmd} S{laser_power:.0f}"

    def trace(coords):
        gcode.append("; Trazando contorno...")
        if len(coords) < 2:
            return
        gcode.append(f"G0 X{coords[0][0]:.3f} Y{coords[0][1]:.3f}")
        gcode.append(full_laser_on_cmd)
        for point in coords[1:]:
            gcode.append(f"G1 X{point[0]:.3f} Y{point[1]:.3f} F{feed_rate}")
        gcode.append(laser_off_cmd)
        gcode.append("")

    def fill(poly):
        gcode.append(f"; Rellenando ...")
        minx, miny, maxx, maxy = poly.bounds
        y = miny
        direction_is_left_to_right = True
        while y <= maxy:
            scanline = LineString([(minx, y), (maxx, y)])
            intersection = poly.intersection(scanline)
            if not intersection.is_empty:
                lines = (
                    list(intersection.geoms)
                    if hasattr(intersection, "geoms")
                    else [intersection]
                )
                lines.sort(
                    key=lambda line: line.coords[0][0],
                    reverse=not direction_is_left_to_right,
                )
                for line in lines:
                    coords = list(line.coords)
                    start_pt, end_pt = (
                        (coords[0], coords[-1])
                        if direction_is_left_to_right
                        else (coords[-1], coords[0])
                    )
                    gcode.append(f"G0 X{start_pt[0]:.3f} Y{start_pt[1]:.3f}")
                    gcode.append(full_laser_on_cmd)
                    gcode.append(f"G1 X{end_pt[0]:.3f} Y{end_pt[1]:.3f} F{feed_rate}")
                    gcode.append(laser_off_cmd)

            direction_is_left_to_right = not direction_is_left_to_right
            y += fill_spacing
        gcode.append("")

    gcode.append(f"; G-code generado por {app_name}")
    gcode.append(f"; Velocidad: {feed_rate}mm/min, Potencia: {laser_power}")
    gcode.append("G21 ; Unidades en mm")
    gcode.append("G90 ; Coordenadas absolutas")
    gcode.append(f"{laser_off_cmd}  ; Apagar láser")
    gcode.append(f"G0 F{fast_move_rate} ; Velocidad de movimiento rápido")
    gcode.append("")

    if geometry.is_empty:
        gcode.append("; No se encontró geometría para generar.")
        return gcode

    min_x, min_y, _, _ = geometry.bounds
    machine_geom = translate(geometry, xoff=-min_x, yoff=-min_y)
    geoms_to_process = (
        list(machine_geom.geoms) if hasattr(machine_geom, "geoms") else [machine_geom]
    )

    for poly in geoms_to_process:
        if not isinstance(poly, Polygon) or poly.is_empty:
            continue
        # Ajuste de la geometría con el offset para no quemar la zona exterior
        # TODO: Esto puede hacer que desaparezcan línea que sean más finas que el offset
        # Estudiar si hay que solucionarlo o lo doy por bueno
        poly_to_process = (
            poly.buffer(offset_distance) if abs(offset_distance) > 1e-6 else poly
        )
        if poly_to_process.is_empty:
            continue
        offset_polygons = (
            list(poly_to_process.geoms)
            if isinstance(poly_to_process, MultiPolygon)
            else [poly_to_process]
        )

        for p in offset_polygons:
            if trace_outline:
                trace(list(p.exterior.coords))
                for interior in p.interiors:
                    trace(list(interior.coords))
            if fill_inner:
                fill(p)

    gcode.append("G0 X0 Y0 ; Volver al origen")
    gcode.append("M2 ; Fin del programa")

    return gcode


def _add_point_to_path(paths, points, color):
    if len(points) > 1:
        paths.append(
            {
                "mode": "stroke",
                "color": (color),
                "points": [points],
            }
        )


def parse_gcode_for_preview(gcode_lines):

    result = DEFAULT_GRAPHIC_INFO.copy()
    g_re = re.compile(r"G([0-3])")
    x_re = re.compile(r"X(-?\d+\.?\d*)")
    y_re = re.compile(r"Y(-?\d+\.?\d*)")

    CMD_TRAVEL = 0
    CMD_WRITE = 1
    travel_color = (255, 255, 0, 200)  # YELLOW
    burn_color = (10, 10, 255, 255)  # BLUE

    # Para saber si estamos viajando o grabando
    current_mode = CMD_TRAVEL

    min_x, min_y, max_x, max_y = 0.0, 0.0, 0.0, 0.0
    current_x, current_y = 0.0, 0.0
    paths = []
    points = [(current_x, current_y)]
    for line in gcode_lines:
        # clean_line = line.split(";")[0].strip().upper()
        clean_line = re.sub(r"\([^)]*\)|;.*$", "", line).strip().upper()
        if not clean_line:
            continue

        g_match = g_re.search(clean_line)
        if not g_match:
            continue

        cmd_val = int(g_match.group(1))
        if cmd_val > CMD_WRITE:
            continue
        start_pos = (current_x, current_y)

        if cmd_val != current_mode:
            _add_point_to_path(
                paths,
                points,
                travel_color if current_mode == CMD_TRAVEL else burn_color,
            )
            points = [start_pos]
            current_mode = cmd_val

        x_match = x_re.search(clean_line)
        y_match = y_re.search(clean_line)

        if x_match:
            current_x = float(x_match.group(1))
        if y_match:
            current_y = float(y_match.group(1))

        end_pos = (current_x, current_y)
        if current_x > max_x:
            max_x = current_x
        if current_y > max_y:
            max_y = current_y
        if current_x < min_x:
            min_x = current_x
        if current_y < min_y:
            min_y = current_y

        if start_pos == end_pos:
            continue

        points.append(end_pos)
    # Guardo el último trazo
    _add_point_to_path(
        paths, points, travel_color if current_mode == CMD_TRAVEL else burn_color
    )
    result["bounds"] = (min_x, min_y, max_x, max_y)
    result["polygons"] = paths
    return result
