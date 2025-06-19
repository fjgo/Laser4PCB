import threading
import wx
import wx.adv
import app_base as ab
from gcode_generator import generate_gcode, parse_gcode_for_preview
from grbl_communicator import GrblCommunicator
from settings_dialog import EVT_CONFIG_UPDATED, SettingsDialog
from utils import (
    build_wildcard,
    geometry_to_polygons,
    get_filename_from_fileDialog,
    primitives_to_geometry,
)
import logging
from gerber_parser import GerberParser
from vector_canvas import VectorCanvas
from pathlib import Path


global _


class L4PFrame(wx.Frame):
    def __init__(self, parent, **kwds):
        super(L4PFrame, self).__init__(parent, **kwds)

        self.primitives = []
        self.gcode_lines = []
        self.grbl = GrblCommunicator()
        self.communication_thread = None

        self.panel = None
        self.notebook = None
        self.controls_panel = None
        self.log_text = None

        # IDs para Menús y Atajos
        self.ID_TAB_GERBER = wx.NewIdRef()
        self.ID_TAB_GCODE = wx.NewIdRef()
        self.ID_MNU_OPEN_ZIP = wx.NewIdRef()
        self.ID_MNU_LOAD_GCODE = wx.NewIdRef()
        self.ID_MNU_SAVE_GCODE = wx.NewIdRef()
        self.ID_MNU_SAVE_IMG = wx.NewIdRef()
        self.ID_MNU_CTRL_SET_HOME = wx.NewIdRef()
        self.ID_MNU_GO_HOME = wx.NewIdRef()
        self.ID_MNU_CTRL_SEND = wx.NewIdRef()

        self.status_queue = []
        self.status_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnClearStatus, self.status_timer)

        self.init_ui()
        self._enable_movement_controls(False)

        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.OnNotebookPageChanged)
        self.Bind(EVT_CONFIG_UPDATED, self.on_config_updated)
        self.Bind(wx.EVT_UPDATE_UI, self.OnUpdateUI)

    def init_ui(self):
        """Construye la interfaz de usuario principal."""
        self.createMenu()
        self.create_layout()
        self.Centre()

    def create_layout(self):
        """Crea el layout principal de la ventana usando un SplitterWindow."""
        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        splitter.SetSashGravity(1.0)

        # --- Panel Superior ---
        top_panel = wx.Panel(splitter, name="top_panel")
        self.panel = top_panel

        top_sizer = wx.BoxSizer(wx.HORIZONTAL)
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        controls_box = wx.StaticBoxSizer(wx.VERTICAL, top_panel, _("Movement"))
        self.create_buttons_layout(controls_box)
        left_sizer.Add(controls_box, 0, wx.EXPAND | wx.ALL, 5)

        gcode_box = wx.StaticBoxSizer(wx.VERTICAL, top_panel, _("GCode"))

        gcode_box.Add(self.create_option_gcode(), 1, wx.EXPAND | wx.ALL, 5)

        left_sizer.Add(gcode_box, 0, wx.EXPAND | wx.ALL, 5)

        top_sizer.Add(left_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # Vista principal (Notebook)
        self.notebook = self.create_view_layout()
        top_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)

        top_panel.SetSizer(top_sizer)

        # Panel Inferior (Log y Conexión)
        bottom_panel = wx.Panel(splitter, style=wx.BORDER_SUNKEN, name="bottom_panel")

        main_bottom_sizer = wx.BoxSizer(wx.VERTICAL)

        connection_log_box = wx.StaticBoxSizer(
            wx.HORIZONTAL, bottom_panel, _("Connection")
        )

        comm_panel = self.create_comm_layout(bottom_panel)
        connection_log_box.Add(
            comm_panel, proportion=0, flag=wx.EXPAND | wx.ALL, border=5
        )

        self.log_text = wx.TextCtrl(
            bottom_panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL
        )

        connection_log_box.Add(self.log_text, proportion=1, flag=wx.EXPAND)

        main_bottom_sizer.Add(
            connection_log_box, proportion=1, flag=wx.EXPAND | wx.ALL, border=10
        )

        bottom_panel.SetSizer(main_bottom_sizer)

        splitter.SplitHorizontally(top_panel, bottom_panel, -150)
        top_panel.SetMinSize(top_panel.GetBestSize())
        bottom_panel.SetMinSize(bottom_panel.GetBestSize())

        self.CreateStatusBar()

    def createMenu(self):
        # Estructura de datos: (ID, "Etiqueta\tAtajo", "Descripción para la barra de estado", manejador)
        menu_data = [
            (
                _("&File"),
                [
                    (
                        wx.ID_OPEN,
                        _("Open Gerber file\tCtrl+G"),
                        _("Open a Gerber file"),
                        self.OnAbrirGerber,
                    ),
                    # (
                    #     self.ID_MNU_OPEN_ZIP,
                    #     _("Open ZIP file\tCtrl+Z"),
                    #     _("Open a zip file with layers"),
                    #     self.OnAbrirZip,
                    # ),
                    (wx.ID_SEPARATOR,),
                    (
                        self.ID_MNU_LOAD_GCODE,
                        _("Load .gcode\tCtrl+O"),
                        _("Load a gcode file"),
                        self.OnCargarGCode,
                    ),
                    (
                        self.ID_MNU_SAVE_GCODE,
                        _("Save .gcode\tCtrl+S"),
                        _("Save the generated gcode"),
                        self.OnGuardarGCode,
                    ),
                    # (
                    #     self.ID_MNU_SAVE_IMG,
                    #     _("Save image\tCtrl+I"),
                    #     _("Save a current view capture"),
                    #     self.OnGuardarImagen,
                    # ),
                    (wx.ID_SEPARATOR,),
                    (
                        wx.ID_EXIT,
                        _("Exit\tCtrl+Q"),
                        _("Get out of application"),
                        self.OnQuit,
                    ),
                ],
            ),
            (
                _("&Edit"),
                [
                    (
                        wx.ID_PREFERENCES,
                        _("Preferences\tCtrl+P"),
                        _("Open configuration dialog"),
                        self.OnConfiguracion,
                    )
                ],
            ),
            (
                _("&Control"),
                [
                    (
                        self.ID_MNU_CTRL_SET_HOME,
                        _("Set origin\tCtrl+R"),
                        _("Set current position as origin (0,0)"),
                        self.OnSetOrigin,
                    ),
                    (
                        self.ID_MNU_GO_HOME,
                        _("Go to origin\tCtrl+H"),
                        _("Go to origin (0,0)"),
                        self.OnGoHome,
                    ),
                    (
                        self.ID_MNU_CTRL_SEND,
                        _("Send\tCtrl+E"),
                        _("Send to engraver"),
                        self.OnSend,
                    ),
                ],
            ),
            (
                _("&Help"),
                [
                    (
                        wx.ID_ABOUT,
                        _("About\tF1"),
                        _("Application information"),
                        self.OnAbout,
                    )
                ],
            ),
        ]

        menubar = wx.MenuBar()
        for menu_label, menu_items in menu_data:
            menu = wx.Menu()
            for item_data in menu_items:
                if item_data[0] == wx.ID_SEPARATOR:
                    menu.AppendSeparator()
                else:
                    # Desempaquetamos los 4 elementos
                    item_id, item_label, item_help, handler = item_data
                    menu_item = wx.MenuItem(menu, item_id, item_label, item_help)
                    menu.Append(menu_item)
                    self.Bind(wx.EVT_MENU, handler, menu_item)
            menubar.Append(menu, menu_label)

        self.SetMenuBar(menubar)

    def create_comm_layout(self, panel):
        # El panel contenedor para los controles de comunicación
        comm_panel = wx.Panel(panel, style=wx.BORDER_NONE, name="comm_panel")

        # --- Crear los widgets ---
        port_label = wx.StaticText(comm_panel, label=_("Port:"))
        self.port_combo = wx.ComboBox(
            comm_panel,
            choices=GrblCommunicator.get_available_ports(),
            style=wx.CB_READONLY,
        )

        speed_label = wx.StaticText(comm_panel, label=_("Speed:"))

        # Lista de velocidades de puerto serie (baud rates) comunes
        common_baud_rates = [
            "115200",
            "57600",
            "38400",
            "19200",
            "9600",
            "4800",
            "2400",
            "1200",
            "300",
        ]

        self.speed_combo = wx.ComboBox(
            comm_panel,
            choices=common_baud_rates,
            style=wx.CB_READONLY,
        )
        self.speed_combo.SetValue("115200")  # Valor por defecto para GRBL

        self.connect_btn = wx.Button(comm_panel, label=_("Connect"))

        # Precalculo el tamaño del texto más largo para que el botón no se quede pequeño al cambiar
        w1, h1 = self.connect_btn.GetTextExtent(_("Connect"))
        w2, h2 = self.connect_btn.GetTextExtent(_("Disconnect"))
        w = w1 if w1 > w2 else w2
        best_width = w + 20

        self.connect_btn.SetMinSize(wx.Size(best_width, -1))

        gb_sizer = wx.GridBagSizer(5, 5)

        gb_sizer.Add(
            port_label, pos=(0, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        gb_sizer.Add(self.port_combo, pos=(0, 1), flag=wx.EXPAND)
        gb_sizer.Add(
            speed_label, pos=(1, 0), flag=wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL
        )
        gb_sizer.Add(self.speed_combo, pos=(1, 1), flag=wx.EXPAND)
        gb_sizer.Add(self.connect_btn, pos=(0, 2), span=(2, 1), flag=wx.EXPAND)

        gb_sizer.AddGrowableCol(1, 1)

        comm_panel.SetSizer(gb_sizer)
        self.connect_btn.Bind(wx.EVT_BUTTON, self.on_connect)

        return comm_panel

    def populate_grid(self, grid, panel, buttons_data):
        for label, command, tooltip in buttons_data:
            if isinstance(command, str):
                handler = lambda event, cmd=command: self.OnMovementCommand(event, cmd)
            else:
                handler = command
            button = wx.Button(panel, size=(60, 60), label=label)
            button.SetToolTip(tooltip)
            button.Bind(wx.EVT_BUTTON, handler)
            grid.Add(button, 0, wx.EXPAND)

    def create_buttons_layout(self, parent_sizer):
        self.controls_panel = wx.Panel(self.panel, style=wx.BORDER_NONE)
        controls_sizer = wx.BoxSizer(wx.VERTICAL)

        def get_move(command):
            return lambda event, cmd=command: self.OnMovementCommand(event, cmd)

        move_buttons = [
            ("↖️", get_move("UpLeft"), _("Move up and left (X-, Y+)")),
            ("⬆️", get_move("Up"), _("Move up (Y+)")),
            ("↗️", get_move("UpRight"), _("Move up and right (X+, Y+)")),
            ("⬅️", get_move("Left"), _("Move left (X-)")),
            ("⏹️", get_move("Stop"), _("Stop movement")),
            ("➡️", get_move("Right"), _("Move right (X+)")),
            ("↙️", get_move("DownLeft"), _("Move down and left (X-, Y-)")),
            ("⬇️", get_move("Down"), _("Move down (Y-)")),
            ("↘️", get_move("DownRight"), _("Move down and right (X+, Y-)")),
        ]

        action_buttons = [
            ("🎯", self.OnSetOrigin, _("Set current position as origin (0,0)")),
            ("🏠", self.OnGoHome, _("Go to origin (0,0)")),
            ("⏯️", self.OnSend, _("Send")),
        ]

        movement_grid = wx.GridSizer(3, 3, 8, 8)
        action_grid = wx.GridSizer(1, 3, 8, 8)

        self.populate_grid(movement_grid, self.controls_panel, move_buttons)
        self.populate_grid(action_grid, self.controls_panel, action_buttons)

        controls_sizer.Add(movement_grid, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        controls_sizer.Add(action_grid, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        self.controls_panel.SetSizer(controls_sizer)
        parent_sizer.Add(self.controls_panel, 1, wx.EXPAND | wx.ALL, 5)

    def create_view_layout(self):
        notebook = wx.Notebook(self.panel)
        self.canvas_gerber = VectorCanvas(
            notebook, name="gerber", default_text=_("Rendering area for Gerber")
        )
        notebook.AddPage(self.canvas_gerber, _("Gerber"))
        self.canvas_gcode = VectorCanvas(
            notebook, name="gcode", default_text=_("Rendering area for GCode")
        )
        notebook.AddPage(self.canvas_gcode, _("GCode"))

        accel_entries = [
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("1"), self.ID_TAB_GERBER),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord("2"), self.ID_TAB_GCODE),
        ]
        accel_table = wx.AcceleratorTable(accel_entries)
        self.SetAcceleratorTable(accel_table)

        return notebook

    def create_option_gcode(self):
        gcode_grid_sizer = wx.FlexGridSizer(rows=4, cols=2, vgap=8, hgap=15)
        gcode_grid_sizer.AddGrowableCol(1)

        for key, item in {
            "trace_outline": _("Trace Outline"),
            "fill_inner": _("Fill Interior"),
            "invert_layer": _("Invert Layer"),
        }.items():
            chk = wx.CheckBox(self.panel, label=item, name=key)
            chk.SetValue(app.config.getboolean("GCode", key))
            self.Bind(wx.EVT_CHECKBOX, self.on_changed_options_gcode, chk)
            gcode_grid_sizer.Add(chk, 0, wx.ALIGN_CENTER_VERTICAL)
            gcode_grid_sizer.AddSpacer(0)

        return gcode_grid_sizer

    def OnUpdateUI(self, event):
        eventId = event.GetId()
        is_connected = self.grbl.is_connected()
        has_primitives = len(self.primitives) > 0

        if eventId in (self.ID_MNU_SAVE_GCODE, self.ID_MNU_SAVE_IMG):
            event.Enable(has_primitives)
        elif eventId in (
            self.ID_MNU_CTRL_SET_HOME,
            self.ID_MNU_GO_HOME,
            self.ID_MNU_CTRL_SEND,
        ):
            event.Enable(is_connected)
        else:
            event.Skip()

    def OnNotebookPageChanged(self, event):
        self.Layout()
        event.Skip()

    def on_changed_options_gcode(self, event):
        checkbox = event.GetEventObject()
        app.config["GCode"][checkbox.Name] = repr(checkbox.Value)
        if checkbox.Name == "invert_layer":
            self._process_gerber()
        self._process_gcode()
        event.Skip()

    def on_config_updated(self, event):
        need_update = False
        for item in ("trace_outline", "fill_inner"):
            checkbox = self.FindWindow(item)
            if checkbox and checkbox.Value != app.config["GCode"].getboolean(
                checkbox.Name
            ):
                need_update = True
                checkbox.Value = app.config["GCode"].getboolean(checkbox.Name)
        if need_update:
            self._process_gcode()
        event.Skip()

    def OnAbrirGerber(self, event):
        try:
            with wx.FileDialog(
                self,
                _("Open Gerber file"),
                wildcard=build_wildcard(
                    (
                        (_("Gerber files"), "*.g*"),
                        (_("Top layer"), "*.gtl"),
                        (_("Bottom layer"), "*.gbl"),
                        (_("Top solder mask"), "*.gts"),
                        (_("Bottom solder mask"), "*.gbs"),
                        (_("Top silkscreen"), "*.gto"),
                        (_("Bottom silkscreen"), "*.gbo"),
                        (_("Top paste"), "*.gtp"),
                        (_("Bottom paste"), "*.gbp"),
                        (_("Keep-out layer"), "*.gko"),
                        (
                            _("Mechanical layers"),
                            "*.gm1;*.gm2;*.gm3;*.gm4;*.gm5;*.gm6;*.gm7;*.gm8;*.gm9",
                        ),
                        (_("Top Pad Master"), "*.gpt"),
                        (_("Bottom Pad Master"), "*.gpb"),
                        (_("All files"), "*.*"),
                    )
                ),
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,  # | wx.FD_MULTIPLE,
            ) as fileDialog:
                if fileDialog.ShowModal() == wx.ID_CANCEL:
                    logging.debug("Gerber file opening canceled by the user.")
                    return
                paths = [Path(p) for p in fileDialog.GetPaths()]
                list_paths = ", ".join(p.name for p in paths)
                num_files = len(paths)
                info = _(
                    "Selected {num_files} Gerber file: {list_paths}",
                    "Selected {num_files} Gerber files: {list_paths}",
                    num_files,
                ).format(num_files=num_files, list_paths=list_paths)
                self.set_status(info)
                logging.info(info)
                self._load_gerber(paths)
        except Exception as e:
            error = _("Error opening Gerber file: {e}").format(e=e)
            logging.error(error)
            self.set_status(error, high_priority=True)

    def OnAbrirZip(self, event):
        try:
            with wx.FileDialog(
                self,
                _("Open ZIP file"),
                wildcard=build_wildcard(((_("ZIP files"), "*.zip"),)),
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
            ) as fileDialog:
                if fileDialog.ShowModal() == wx.ID_CANCEL:
                    logging.debug("ZIP file opening canceled by the user.")
                    return
                pathname = Path(fileDialog.GetPath())

                info = _("Opening ZIP: {pathname}").format(pathname=pathname.name)
                self.set_status(info)
                logging.info(info)
        except Exception as e:
            error = _("Error opening ZIP file: {e}").format(e=e)
            logging.error(error)
            self.set_status(error, high_priority=True)

    def OnCargarGCode(self, event):
        with wx.FileDialog(
            self,
            _("Load GCODE file"),
            wildcard=build_wildcard(((_("GCODE files"), "*.gcode;*.nc"),)),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                logging.debug("GCODE loading canceled by the user.")
                return
            pathname = Path(get_filename_from_fileDialog(fileDialog))
            info = _("Loading GCODE from: {pathname}").format(pathname=pathname.name)

            try:
                self.gcode_lines = pathname.read_text().splitlines()
                self.canvas_gcode.set_graphic_info(
                    parse_gcode_for_preview(self.gcode_lines)
                )
                self.set_status(info)
                logging.info(info)
            except IOError as e:
                error = _("Error loading GCODE file {filename}: {e}").format(
                    filename=pathname.name, e=e
                )
                logging.error(error)
                self.set_status(error, high_priority=True)

    def OnGuardarGCode(self, event):
        with wx.FileDialog(
            self,
            _("Save GCODE file"),
            wildcard=build_wildcard(((_("GCODE files"), "*.gcode;*.nc"),)),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                logging.debug("GCODE saving canceled by the user.")
                return
            pathname = Path(get_filename_from_fileDialog(fileDialog))
            info = _("Saving GCODE in: {pathname}").format(pathname=pathname.name)

            try:
                pathname.write_text("\n".join(self.gcode_lines))
                self.set_status(info)
                logging.info(info)
            except IOError as e:
                error = _("Error saving GCODE file {filename}: {e}").format(
                    filename=pathname.name, e=e
                )
                logging.error(error)
                self.set_status(error, high_priority=True)

    def OnGuardarImagen(self, event):
        try:
            with wx.FileDialog(
                self,
                _("Save image"),
                wildcard=build_wildcard(
                    ((_("PNG Images"), "*.png"), (_("JPG Images"), "*.jpg"))
                ),
                style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            ) as fileDialog:
                if fileDialog.ShowModal() == wx.ID_CANCEL:
                    logging.debug("Image saving canceled by the user.")
                    return

                pathname = Path(get_filename_from_fileDialog(fileDialog))
                info = _("Saving image in: {pathname}").format(pathname=pathname.name)
                self.set_status(info)
                logging.info(info)

                self.canvas_gerber.save_to_file(str(pathname))

        except Exception as e:
            error = _("Error saving image: {e}").format(e=e)
            logging.error(error)
            self.set_status(error, high_priority=True)

    def OnConfiguracion(self, event):
        self.set_status(_("Opening configuration"))
        with SettingsDialog(self, app.config) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.set_status(_("Updated configuration"))
            else:
                self.set_status(_("Canceled by the user"))

    def OnQuit(self, event):
        self.Close()

    def OnAbout(self, event):
        about_info = wx.adv.AboutDialogInfo()
        about_info.SetVersion(app.__version__)
        about_info.SetDescription(
            _(
                "An application to generate GCODE from Gerber \nand send it to a laser engraver."
            )
        )
        about_info.SetCopyright("© 2025 Francisco García")
        wx.adv.AboutBox(about_info, self)

    def on_connect(self, event):
        port = self.port_combo.GetValue()
        speed = self.speed_combo.GetValue()
        if not port:
            self.log_message("Por favor, selecciona un puerto.")
            return

        if self.grbl.serial_port and self.grbl.serial_port.is_open:
            self.grbl.disconnect()
            self.connect_btn.SetLabel(_("Connect"))
            self._enable_movement_controls(False)
            self.log_message(_("Disconnected."))
        else:
            self.log_message(_("Trying to connect to {port}...").format(port=port))
            self.communication_thread = threading.Thread(
                target=self._connect_thread, args=(port, speed)
            )
            self.communication_thread.start()

    def OnMovementCommand(self, event, command_name):
        self.set_status(_("Move head: {command}").format(command=command_name))
        commands = {
            "UpLeft": "G91 G0 X-10Y10 F3000",
            "Up": "G91 G0 Y10 F3000",
            "UpRight": "G91 G0 X10Y10 F3000",
            "Left": "G91 G0 X-10 F3000",
            "Stop": b"\x18",
            "Right": "G91 G0 X10 F3000",
            "DownLeft": "G91 G0 X-10Y-10 F3000",
            "Down": "G91 G0 Y-10 F3000",
            "DownRight": "G91 G0 X10Y-10 F3000",
        }
        command = commands.get(command_name)
        if command:
            self.grbl.send_command(command)

    def OnSetOrigin(self, event):
        self.set_status(_("Setting origin"))
        self.grbl.send_command("G92 X0 Y0 Z0")

    def OnGoHome(self, event):
        self.set_status(_("Going to origin"))
        self.grbl.send_command("G28")

    def OnSend(self, event):
        self.set_status(_("Sending..."))
        self.grbl.stream_gcode_text(self.gcode_lines)

    def _load_gerber(self, paths):
        for file in paths:
            self.notebook.SetSelection(0)
            gerber = GerberParser()
            gerber.parse(filepath=str(file))
            self.primitives = gerber.get_primitives()
            self._process_gerber()
            self._process_gcode()

    def _process_gerber(self):
        self.geometry = primitives_to_geometry(
            self.primitives,
            invert_polarity=app.config["GCode"].getboolean("invert_layer"),
        )
        self.canvas_gerber.set_graphic_info(geometry_to_polygons((self.geometry)))

    def _process_gcode(self):
        if self.primitives:
            self.gcode_lines = generate_gcode(
                self.geometry, app.get_config(), app.AppName
            )
            self.canvas_gcode.set_graphic_info(
                parse_gcode_for_preview(self.gcode_lines)
            )

    def _connect_thread(self, port, speed):
        if self.grbl.connect(port, speed):
            wx.CallAfter(
                self.log_message,
                _("Connected to {port} at {speed} bps. GRBL ready.").format(
                    port=port, speed=speed
                ),
            )
            wx.CallAfter(self.connect_btn.SetLabel, _("Disconnect"))
            wx.CallAfter(self._enable_movement_controls, True)
        else:
            wx.CallAfter(
                self.log_message,
                _("The connection to {port} failed.").format(port=port),
            )
            wx.CallAfter(self.connect_btn.SetLabel, _("Connect"))
            wx.CallAfter(self._enable_movement_controls, False)

    def _enable_movement_controls(self, enable):
        if self.controls_panel:
            for child in self.controls_panel.GetChildren():
                if isinstance(child, (wx.Button, wx.StaticBitmap)):
                    child.Enable(enable)

    def log_message(self, message):
        wx.CallAfter(self._do_log_message, message)

    def _do_log_message(self, message):
        if self.log_text:
            self.log_text.AppendText(message + "\n")

    def set_status(self, msg, high_priority=False):
        if high_priority:
            self.status_timer.Stop()
            self.status_queue.insert(0, msg)
            self._show_next_status()
        else:
            self.status_queue.append(msg)
            if not self.status_timer.IsRunning():
                self._show_next_status()

    def _show_next_status(self):
        if self.status_queue:
            msg = self.status_queue.pop(0)
            self.SetStatusText(msg)
            self.status_timer.Start(3000, oneShot=True)
        else:
            self.SetStatusText("")

    def OnClearStatus(self, event):
        self._show_next_status()


if __name__ == "__main__":
    app = ab.BaseApp(redirect=False)
    frame = L4PFrame(None, title=app.AppDisplayName, size=(1024, 768))
    frame.SetMinSize((600, 600))
    frame.Show()
    app.MainLoop()
