import wx

DEFAULT_GRAPHIC_INFO = {"bounds": (0, 0, 0, 0), "polygons": []}

global _


class VectorCanvas(wx.Panel):
    def __init__(self, parent, graphic_info=None, default_text=None, **kwargs):
        super(VectorCanvas, self).__init__(parent, **kwargs)
        self.text = default_text if default_text != None else _("Rendering area")

        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.dragging = False
        self.last_mouse_pos = None
        self.has_valid_content = False
        self.set_graphic_info(graphic_info)

        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_mouse_wheel)
        self.Bind(wx.EVT_MOTION, self.on_mouse_move)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_LEFT_DCLICK, self.on_left_dclick)
        self.Bind(wx.EVT_SIZE, self.on_resize)

    def set_graphic_info(self, graphic_info):
        """Cambia la geometría y ajusta el zoom automáticamente."""
        self.graphic_info = dict(
            graphic_info
            if graphic_info is not None
            and "bounds" in graphic_info
            and "polygons" in graphic_info
            else DEFAULT_GRAPHIC_INFO
        )
        self.has_valid_content = len(self.graphic_info["polygons"]) > 0
        self.zoom_to_fit()
        self.Refresh()

    def zoom_to_fit(self):
        """Ajusta el zoom y el pan para que la geometría ocupe toda la vista."""
        canvas_w, canvas_h = self.GetClientSize()
        if canvas_w == 0 or canvas_h == 0:
            return
        if not self.has_valid_content:
            self.graphic_info["bounds"] = [0, 0, canvas_w, canvas_h]
            return
        min_x, min_y, max_x, max_y = self.graphic_info["bounds"]
        world_w = max_x - min_x if max_x > min_x else 1.0
        world_h = max_y - min_y if max_y > min_y else 1.0

        scale_x = canvas_w / world_w
        scale_y = canvas_h / world_h
        self.scale = min(scale_x, scale_y) * 0.95
        world_cx = min_x + world_w / 2.0
        world_cy = min_y + world_h / 2.0
        self.offset_x = canvas_w / 2 - world_cx * self.scale
        self.offset_y = canvas_h / 2 + world_cy * self.scale

    def get_transform_matrix(self):
        matrix = wx.GraphicsRenderer.GetDefaultRenderer().CreateMatrix()
        matrix.Translate(self.offset_x, self.offset_y)
        matrix.Scale(self.scale, -self.scale)
        return matrix

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush((235, 235, 235)))

        gc = wx.GraphicsContext.Create(dc)

        # gc.BeginLayer(1.0)
        dc.Clear()

        if self.has_valid_content:
            mat = self.get_transform_matrix()
            gc.SetTransform(mat)
            self.draw(gc)
        else:
            if self.text != "":
                font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
                font.SetPointSize(20)
                font.SetWeight(wx.FONTWEIGHT_LIGHT)
                gc.SetFont(font, wx.BLACK)
                _, _, canvas_w, canvas_h = self.graphic_info["bounds"]
                tw, th = gc.GetTextExtent(self.text)
                gc.DrawText(self.text, (canvas_w - tw) / 2, (canvas_h - th) / 2)

        # gc.EndLayer()

    def draw(self, gc):
        cut_width = 1.0 / self.scale
        for poly in self.graphic_info["polygons"]:
            polygon = poly["points"]
            current_color = poly["color"]
            path = gc.CreatePath()
            exterior_coords = list(polygon[0])
            path.MoveToPoint(exterior_coords[0])
            for point in exterior_coords[1:]:
                path.AddLineToPoint(point)
            path.CloseSubpath()
            if len(polygon) > 1:
                for interior in polygon[1:]:
                    interior_coords = list(interior)
                    path.MoveToPoint(interior_coords[0])
                    for point in interior_coords[1:]:
                        path.AddLineToPoint(point)
                    path.CloseSubpath()
            if poly["mode"] == "fill":
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.SetBrush(wx.Brush(wx.Colour(*current_color)))
                gc.DrawPath(path, fillStyle=wx.WINDING_RULE)
            else:
                cut_pen = gc.CreatePen(
                    wx.GraphicsPenInfo(current_color, cut_width, wx.PENSTYLE_SOLID)
                )
                gc.SetPen(cut_pen)
                gc.StrokePath(path)

    def on_mouse_wheel(self, event):
        zoom_factor = 1.1
        mouse_pos = event.GetPosition()
        # Coordenadas del mouse en el sistema de coordenadas del mundo antes del zoom
        xw = (mouse_pos.x - self.offset_x) / self.scale
        yw = (mouse_pos.y - self.offset_y) / self.scale
        if event.GetWheelRotation() > 0:
            self.scale *= zoom_factor
        else:
            self.scale /= zoom_factor
        # Ajusta el offset para que el punto bajo el cursor siga bajo el cursor
        self.offset_x = mouse_pos.x - xw * self.scale
        self.offset_y = mouse_pos.y - yw * self.scale
        self.Refresh()

    def on_left_dclick(self, event):
        self.zoom_to_fit()
        self.Refresh()

    def on_left_down(self, event):
        self.dragging = True
        self.last_mouse_pos = event.GetPosition()

    def on_left_up(self, event):
        self.dragging = False

    def on_mouse_move(self, event):
        if self.dragging and self.last_mouse_pos is not None:
            dx = event.GetX() - self.last_mouse_pos.x
            dy = event.GetY() - self.last_mouse_pos.y
            self.offset_x += dx
            self.offset_y += dy
            self.last_mouse_pos = event.GetPosition()
            self.Refresh()

    def on_resize(self, event):
        if not self.has_valid_content:
            canvas_w, canvas_h = self.GetClientSize()
            self.graphic_info["bounds"] = [0, 0, canvas_w, canvas_h]
        event.Skip()
