import wx
import wx.lib.newevent
import configparser

global _

# Define un evento personalizado para indicar que la configuración ha sido guardada.
# Nos sirve para notificar a la ventana principal cuándo el diálogo ha actualizado la configuración.
ConfigUpdatedEvent, EVT_CONFIG_UPDATED = wx.lib.newevent.NewCommandEvent()


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, config):
        super().__init__(parent, wx.ID_ANY, _("Preferences"), size=(550, 600))
        # Config es el ConfigParser de la aplicación
        self.config = config

        self.InitUI()
        self.CentreOnParent()

    def InitUI(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        engraver_box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Engraver"))
        self.add_engraver_controls(engraver_box)
        main_sizer.Add(engraver_box, 0, wx.EXPAND | wx.ALL, 10)

        gcode_box = wx.StaticBoxSizer(wx.VERTICAL, self, _("GCode"))
        self.add_gcode_controls(gcode_box)
        main_sizer.Add(gcode_box, 0, wx.EXPAND | wx.ALL, 10)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        button_sizer.Add(
            self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL, 5
        )
        self.Bind(wx.EVT_BUTTON, self.on_save)

        main_sizer.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 10)

        self.SetSizerAndFit(main_sizer)

    def add_engraver_controls(self, sizer_parent):
        grid_sizer = wx.FlexGridSizer(rows=5, cols=2, vgap=8, hgap=15)
        grid_sizer.AddGrowableCol(1)

        grid_sizer.Add(
            wx.StaticText(self, label=_("Advance speed (mm/min):")),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.feed_rate_ctrl = wx.TextCtrl(
            self, value=str(self.config.getint("Engraver", "feed_rate"))
        )
        grid_sizer.Add(self.feed_rate_ctrl, 1, wx.EXPAND)

        grid_sizer.Add(
            wx.StaticText(self, label=_("Speed movement fast (mm/min):")),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.fast_move_rate_ctrl = wx.TextCtrl(
            self, value=str(self.config.getint("Engraver", "fast_move_rate"))
        )
        grid_sizer.Add(self.fast_move_rate_ctrl, 1, wx.EXPAND)

        grid_sizer.Add(
            wx.StaticText(self, label=_("Laser Power (0-1000):")),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        power_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.laser_power_slider = wx.Slider(
            self,
            value=self.config.getint("Engraver", "laser_power"),
            minValue=0,
            maxValue=1000,
            style=wx.SL_HORIZONTAL | wx.SL_LABELS,
        )
        power_sizer.Add(self.laser_power_slider, 1, wx.EXPAND)
        grid_sizer.Add(power_sizer, 1, wx.EXPAND)

        grid_sizer.Add(
            wx.StaticText(self, label=_("Laser Command ON:")),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.laser_on_cmd_ctrl = wx.TextCtrl(
            self, value=self.config.get("Engraver", "laser_on_cmd")
        )
        grid_sizer.Add(self.laser_on_cmd_ctrl, 1, wx.EXPAND)

        grid_sizer.Add(
            wx.StaticText(self, label=_("Laser Command OFF:")),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.laser_off_cmd_ctrl = wx.TextCtrl(
            self, value=self.config.get("Engraver", "laser_off_cmd")
        )
        grid_sizer.Add(self.laser_off_cmd_ctrl, 1, wx.EXPAND)

        sizer_parent.Add(grid_sizer, 1, wx.EXPAND | wx.ALL, 5)

    def add_gcode_controls(self, sizer_parent):
        gcode_grid_sizer = wx.FlexGridSizer(rows=4, cols=2, vgap=8, hgap=15)
        gcode_grid_sizer.AddGrowableCol(1)

        self.trace_outline_chk = wx.CheckBox(self, label=_("Trace Outline"))
        self.trace_outline_chk.SetValue(
            self.config.getboolean("GCode", "trace_outline")
        )
        gcode_grid_sizer.Add(self.trace_outline_chk, 0, wx.ALIGN_CENTER_VERTICAL)

        gcode_grid_sizer.AddSpacer(0)

        self.fill_inner_chk = wx.CheckBox(self, label=_("Fill Interior"))
        self.fill_inner_chk.SetValue(self.config.getboolean("GCode", "fill_inner"))
        gcode_grid_sizer.Add(self.fill_inner_chk, 0, wx.ALIGN_CENTER_VERTICAL)
        gcode_grid_sizer.AddSpacer(0)

        gcode_grid_sizer.Add(
            wx.StaticText(self, label=_("Displacement Distance:")),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.offset_distance_ctrl = wx.TextCtrl(
            self, value=str(self.config.getfloat("GCode", "offset_distance"))
        )
        gcode_grid_sizer.Add(self.offset_distance_ctrl, 1, wx.EXPAND)

        gcode_grid_sizer.Add(
            wx.StaticText(self, label=_("Filling Spacing:")),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.fill_spacing_ctrl = wx.TextCtrl(
            self, value=str(self.config.getfloat("GCode", "fill_spacing"))
        )
        gcode_grid_sizer.Add(self.fill_spacing_ctrl, 1, wx.EXPAND)

        sizer_parent.Add(gcode_grid_sizer, 1, wx.EXPAND | wx.ALL, 5)

    def on_save(self, event):
        if event.Id == wx.ID_OK:
            try:
                # Validaciones para campos numéricos
                feed_rate = int(self.feed_rate_ctrl.GetValue())
                fast_move_rate = int(self.fast_move_rate_ctrl.GetValue())
                offset_distance = float(self.offset_distance_ctrl.GetValue())
                fill_spacing = float(self.fill_spacing_ctrl.GetValue())

                self.config.set("Engraver", "feed_rate", str(feed_rate))
                self.config.set("Engraver", "fast_move_rate", str(fast_move_rate))
                self.config.set(
                    "Engraver", "laser_power", str(self.laser_power_slider.GetValue())
                )
                self.config.set(
                    "Engraver", "laser_on_cmd", self.laser_on_cmd_ctrl.GetValue()
                )
                self.config.set(
                    "Engraver", "laser_off_cmd", self.laser_off_cmd_ctrl.GetValue()
                )

                self.config.set(
                    "GCode", "trace_outline", str(self.trace_outline_chk.GetValue())
                )
                self.config.set(
                    "GCode", "fill_inner", str(self.fill_inner_chk.GetValue())
                )
                self.config.set("GCode", "offset_distance", str(offset_distance))
                self.config.set("GCode", "fill_spacing", str(fill_spacing))

                # Guardar los cambios
                # Emitir un evento personalizado para notificar a la ventana principal
                evt = ConfigUpdatedEvent(self.GetId())  # Usa el ID del diálogo
                # Envía el evento a la ventana padre
                wx.PostEvent(self.GetParent(), evt)
                event.Skip()

            except ValueError as e:
                wx.MessageBox(
                    _(
                        "Format error in the data. Please ensure to enter valid numbers: {e}"
                    ).format(e=e),
                    _("Error de Validación"),
                    wx.OK | wx.ICON_ERROR,
                )
        else:
            event.Skip()
