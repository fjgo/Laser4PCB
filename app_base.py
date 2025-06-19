# -*- coding: utf-8 -*-
#
# Author:   Francisco García
# Date:     2025-06-01
# Purpose:
#
# Inspired by the I18N wxPython demo and the Internationalization page on
# the wxPython wiki.
#
import builtins
import configparser
import logging
import sys
import os
import wx
from wx.lib.mixins.inspection import InspectionMixin

from settings_dialog import EVT_CONFIG_UPDATED

appName = "Laser4PCB"
__version__ = "1.0.0"

# languages you want to support
supLang = {
    "en": wx.LANGUAGE_ENGLISH,
    "es": wx.LANGUAGE_SPANISH,
}
# add translation macro to builtin similar to what gettext does

builtins.__dict__["_"] = wx.GetTranslation


# Install a custom displayhook to keep Python from setting the global
# _ (underscore) to the value of the last evaluated expression.  If
# we don't do this, our mapping of _ to gettext can get overwritten.
# This is useful/needed in interactive debugging with PyShell.
def _displayHook(obj):
    if obj is not None:
        print(repr(obj))


class BaseApp(wx.App, InspectionMixin):
    def OnInit(self):
        global _
        self.Init()  # InspectionMixin
        self.SetUseBestVisual(True)
        # work around for Python stealing "_"
        sys.displayhook = _displayHook

        self.__version__ = __version__
        self.AppName = appName
        self.config_file = f"{self.AppName}.ini"
        self._load_settings()

        loglevel = logging.getLevelNamesMapping()[self.config["Settings"]["loglevel"]]
        logging.basicConfig(
            level=loglevel,
            format="%(asctime)s [%(levelname)s] - %(funcName)s(%(lineno)d) - %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(self.AppName + ".log", encoding="utf-8"),
            ],
        )

        self.locale = None
        wx.Locale.AddCatalogLookupPathPrefix("locale")
        self.updateLanguage(self.config["Settings"]["Language"])

        self.AppDisplayName = _("Gerber to GCODE converter for laser engraver")
        # Me conecto al evento de cambio de configuración
        self.Bind(EVT_CONFIG_UPDATED, self.on_config_updated)
        return True

    def sanitize_config(self, save=False):
        # Sanear cosas que pueden venir mal
        try:
            logging._nameToLevel[self.config["Settings"]["loglevel"].upper()]
        except Exception as e:
            self.config["Settings"]["loglevel"] = "INFO"
        # "invert_layer" debe ser volátil, solo para la sesión en curso.
        # No queremos guardarlo, peo sí preservarlo dentro de la sesión
        if save:
            invert_layer = self.config["GCode"]["invert_layer"]

        self.config["GCode"]["invert_layer"] = "False"
        if save:
            with open(self.config_file, "w") as configfile:
                self.config.write(configfile)
            self.config["GCode"]["invert_layer"] = invert_layer
            print(f"Configuración guardada en '{self.config_file}'")

    def _load_settings(self):
        self.config = configparser.ConfigParser()
        self.config["Settings"] = {
            "Language": "es",
            "LogLevel": "INFO",
        }
        self.config["Engraver"] = {
            "feed_rate": "3000",
            "fast_move_rate": "6000",
            "laser_power": "1000",
            "laser_on_cmd": "M3",
            "laser_off_cmd": "M5",
        }
        self.config["GCode"] = {
            "trace_outline": "True",
            "fill_inner": "True",
            "offset_distance": "-0.04",
            "fill_spacing": "0.1",
            "invert_layer": "False",
        }
        self.config.read(self.config_file)
        self.sanitize_config()

    def get_config(self):
        """
        Devuelve un diccionario con todas las opciones de configurarión con sus tipos correctos
        """
        config = {}
        Settings = self.config["Settings"]
        config["Settings"] = {
            "Language": Settings["Language"],
            "LogLevel": Settings["LogLevel"],
        }
        Engraver = self.config["Engraver"]
        config["Engraver"] = {
            "feed_rate": Engraver.getint("feed_rate"),
            "fast_move_rate": Engraver.getint("fast_move_rate"),
            "laser_power": Engraver.getint("laser_power"),
            "laser_on_cmd": Engraver["laser_on_cmd"],
            "laser_off_cmd": Engraver["laser_off_cmd"],
        }
        GCode = self.config["GCode"]
        config["GCode"] = {
            "trace_outline": GCode.getboolean("trace_outline"),
            "fill_inner": GCode.getboolean("fill_inner"),
            "offset_distance": GCode.getfloat("offset_distance"),
            "fill_spacing": GCode.getfloat("fill_spacing"),
            "invert_layer": GCode.getboolean("invert_layer"),
        }
        return config

    def save_settings(self):
        """Guarda la configuración actual en el archivo .ini."""
        # Primero me aseguro de no guardar nada incorrecto
        self.sanitize_config(save=True)

    def on_config_updated(self, event):
        self.save_settings()
        event.Skip()  # Permite que el evento se propague si es necesario

    def updateLanguage(self, lang):
        """
        Update the language to the requested one.

        Make *sure* any existing locale is deleted before the new
        one is created.  The old C++ object needs to be deleted
        before the new one is created, and if we just assign a new
        instance to the old Python variable, the old C++ locale will
        not be destroyed soon enough, likely causing a crash.

        :param string `lang`: one of the supported language codes

        """
        # if an unsupported language is requested default to English
        if lang in supLang:
            selLang = supLang[lang]
        else:
            selLang = wx.LANGUAGE_ENGLISH

        if self.locale:
            assert sys.getrefcount(self.locale) <= 2
            del self.locale

        # create a locale object for this language
        self.locale = wx.Locale(selLang)
        if self.locale.IsOk():
            self.locale.AddCatalog(appName)
        else:
            self.locale = None
