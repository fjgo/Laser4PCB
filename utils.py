from shapely import MultiPolygon, Polygon, unary_union
import wx
from wx.svg import SVGimage
from vector_canvas import DEFAULT_GRAPHIC_INFO


def build_button2(bottoms_panel, label, handler, tooltip, btn_size=(60, 60)):
    btn = wx.Button(bottoms_panel, size=btn_size, label=label)
    btn.SetToolTip(tooltip)
    btn.Bind(wx.EVT_BUTTON, handler)
    return btn


def build_button(parent, label, handler, tooltip, icon_path=""):
    if icon_path != "":
        if icon_path.endswith(".svg"):
            img = SVGimage.CreateFromFile(icon_path)
            bmp = img.ConvertToScaledBitmap((16, 16), parent)
        else:
            bmp = wx.Bitmap(icon_path, wx.BITMAP_TYPE_ANY)

        btn = wx.BitmapButton(parent, bitmap=bmp, size=(60, 60))

    else:
        btn = wx.Button(parent, size=(60, 60), label=label)

    btn.SetToolTip(tooltip)
    btn.Bind(wx.EVT_BUTTON, handler)
    return btn


def build_wildcard(files_selector):
    filetypes = ""
    for text, extension in files_selector:
        filetypes += f"{text} ({extension})|{extension}|"
    filetypes = filetypes[:-1]  # Elimino el último '|'
    return filetypes


def get_filename_from_fileDialog(fileDialog: wx.FileDialog):
    # Obtiene todas las extensiones posibles del filtro seleccionado
    wildcards = fileDialog.Wildcard.split("|")
    extensions = []
    for i in range(1, len(wildcards), 2):
        exts = wildcards[i].split(";")
        extensions.append([e.strip().lstrip("*.") for e in exts])
    selected_exts = extensions[fileDialog.FilterIndex]
    pathname = fileDialog.GetPath()
    # Si ya termina con alguna extensión válida, no la añade
    if not any(pathname.lower().endswith(f".{ext.lower()}") for ext in selected_exts):
        pathname += f".{selected_exts[0]}"
    return pathname


def primitives_to_geometry(primitives, invert_polarity=False):
    if not primitives:
        return Polygon()
    min_width = 0.01
    dark_geoms = []
    for prim in primitives:
        geom = prim["shape"]
        # Si es muy delgado (por ejemplo, área muy pequeña o es una línea), engrosar
        if hasattr(geom, "bounds"):
            minx, miny, maxx, maxy = geom.bounds
            width = maxx - minx
            height = maxy - miny
            if width < min_width or height < min_width:
                geom = geom.buffer(min_width / 2, cap_style=1)
        dark_geoms.append(geom)

    final_geometry = unary_union(dark_geoms)

    if invert_polarity:
        if final_geometry.is_empty:
            return Polygon()
        bounds = final_geometry.bounds
        margin = (bounds[2] - bounds[0]) * 0.01 if (bounds[2] - bounds[0]) > 0 else 1.0
        universe = Polygon(
            [
                (bounds[0] - margin, bounds[1] - margin),
                (bounds[2] + margin, bounds[1] - margin),
                (bounds[2] + margin, bounds[3] + margin),
                (bounds[0] - margin, bounds[3] + margin),
            ]
        )
        final_geometry = universe.difference(final_geometry)

    return final_geometry


def geometry_to_polygons(geometry):
    def _draw_polygon(polygon):
        perimeter = {"mode": "fill", "color": (0, 100, 0, 250), "points": []}

        if (
            not hasattr(polygon, "exterior")
            or polygon.exterior is None
            or polygon.is_empty
        ):
            return perimeter
        exterior_coords = list(polygon.exterior.coords)
        if not exterior_coords:
            return perimeter
        points = []
        points.append(exterior_coords)
        for interior in getattr(polygon, "interiors", []):
            interior_coords = list(interior.coords)
            points.append(interior_coords)
        perimeter["points"] = points
        return perimeter

    result = DEFAULT_GRAPHIC_INFO.copy()
    if not geometry.is_empty:
        result["bounds"] = geometry.bounds
        if isinstance(geometry, MultiPolygon):
            polygons = [_draw_polygon(part) for part in geometry.geoms]
        elif isinstance(geometry, Polygon):
            polygons = [_draw_polygon(geometry)]
        else:
            polygons = []
        result["polygons"] = polygons
    return result


def primitives_to_polygons(primitives, invert_polarity=False):
    geometry = primitives_to_geometry(primitives, invert_polarity)
    return geometry_to_polygons(geometry)
