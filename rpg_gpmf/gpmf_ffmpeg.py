#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 10-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm          : gpmf_ffmpeg.py
#  Version           : 2.0
#  Beschreibung      : Keine Beschreibung verfügbar.
#  Zeilen            : 287
#  Abhängigkeiten    : collections, configparser, os, pathlib, platform, re, shutil, subprocess, sys
#  Klassen           : FfmpegConfig, FfmpegTools
# ------------------------------------------------------------------------------
#  Public Methoden:
#    FfmpegConfig                                         → read path of ffmpeg / ffprobe from configuration file
#      load_config_file(l_ffmpeg, l_ffprobe)              → Load config file to check for ffmpeg path overrides
#
#    FfmpegTools                                          → Keine Beschreibung.
#      to_int(str)                                        → Hilfsmethode zur sicheren Konvertierung in einen Integer.
#      run_cmd_raw(cmd, args)                             → Führt einen nativen System-Befehl abgetrennt im Hintergrund aus.
#      call_ffmpeg(list[str])                             → Ruft das konfigurierte FFmpeg-Binary mit Argumenten auf.
#      call_ffprobe(list[str])                            → Ruft das konfigurierte FFprobe-Binary mit Argumenten auf.
# ------------------------------------------------------------------------------
#  Globale Funktionen:
#    get_ffmpeg_service(bool)                             → Gibt die Singleton-Instanz der FfmpegTools zurück.
# ------------------------------------------------------------------------------
#  Copyright (C) 2026 <ralfpeter.bergheim@gmail.com>
# ------------------------------------------------------------------------------

from __future__ import annotations
import sys
import os
import shutil
import re
import platform
from pathlib import Path
from subprocess import run, PIPE, CREATE_NO_WINDOW
from collections import namedtuple
import configparser


# -------------------------------------------------------------------------------------------
# All named tuples
# -------------------------------------------------------------------------------------------
Result = namedtuple('Result', ['code', 'out', 'error'])

# ---------------------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------------------
CONFIGFILE = r'%APPDATA%\gpmf2file\gpmf2file.conf'
CONFIGHOME = 'XDG_CONFIG_HOME'
CONFIGPATH1 = '$XDG_CONFIG_HOME/gpmf2file.conf'
CONFIGPATH2 = '$HOME/.config/gpmf2file.conf'
FFMPEGNAME = "ffmpeg"
FFPROBENAME = "ffprobe"


# ---------------------------------------------------------------------------------------


# ================================================================================
# ================================================================================
class FfmpegConfig:
    """
    read path of ffmpeg / ffprobe from configuration file
    """

    # -------------------------------------------------------------------------------------------
    def __init__(self, ffmpeg=None, ffprobe=None, verbose: bool = False):
        """Kurzbeschreibung für __init__.
        
        :param ffmpeg: (Any) Beschreibung von ffmpeg.
        :param ffprobe: (Any) Beschreibung von ffprobe.
        :param verbose: (bool) Beschreibung von verbose.
        """

        self.ffmpeg_cmd = ffmpeg
        self.ffprobe_cmd = ffprobe
        self.verbose = verbose
        self.load_config_file(ffmpeg, ffprobe)

    # -------------------------------------------------------------------------------------------
    # set ffmpeg, ffprobe from installation or given path
    # -------------------------------------------------------------------------------------------
    @staticmethod
    def _find_installation(l_exe: str, l_cmd: str) -> Path | None:
        """
        Sucht nach einer ausführbaren Datei (z. B. ffmpeg).
        Prüft zuerst den übergebenen Pfad, dann relativ und schließlich im System-PATH.

        :param l_exe: (str) Direkt vorgegebener Pfad zur ausführbaren Datei.
        :param l_cmd: (str) Der Befehlsname (z. B. 'ffmpeg' oder 'ffmpeg.exe').
        :return: (Path | None) Das gefundene Path-Objekt oder None.
        """
        if l_exe:
            check_path = Path(l_exe).resolve()
            if check_path.is_file():
                return check_path

        local_check = Path("../", l_cmd).resolve()
        if local_check.is_file():
            return local_check

        # shutil.which triggert hier fälschlicherweise die PathLike-Deprecation-Warnung der IDE.
        # Da l_cmd ein garantierter 'str' ist, wird die Warnung via '# noqa' sicher unterdrückt.
        found: str | None = shutil.which(l_cmd)  # noqa

        if not found:
            print(f'{l_cmd} fehlt!')
            return None

        return Path(found)

    # -------------------------------------------------------------------------------------------
    def load_config_file(self, l_ffmpeg, l_ffprobe):
        """Load config file to check for ffmpeg path overrides
        
        :param l_ffmpeg: (Any) Beschreibung von l_ffmpeg.
        :param l_ffprobe: (Any) Beschreibung von l_ffprobe.
        """

        windows = platform.system() == 'Windows'

        # find config path depending on OS
        if windows:
            config_path = os.path.expandvars(CONFIGFILE)
        else:
            if os.environ.get(CONFIGHOME, False):
                config_path = os.path.expandvars(CONFIGPATH1)
            else:
                config_path = os.path.expandvars(CONFIGPATH2)

        # read config if it exists
        if os.path.exists(config_path):
            conf = configparser.ConfigParser()
            conf.read(config_path)
            self.ffmpeg_cmd, self.ffprobe_cmd = conf[FFMPEGNAME][FFMPEGNAME], conf[FFMPEGNAME][FFPROBENAME]
        else:
            # otherwise assume ffmpeg and ffprobe are in path, get it
            self.ffmpeg_cmd = FFMPEGNAME + ".exe" if windows else FFMPEGNAME
            self.ffprobe_cmd = FFPROBENAME + ".exe" if windows else FFPROBENAME

            # set ffmpeg, from installation or given path
            self.ffmpeg_cmd = self._find_installation(l_ffmpeg, self.ffmpeg_cmd)
            # set ffprobe, from installation or given path
            self.ffprobe_cmd = self._find_installation(l_ffprobe, self.ffprobe_cmd)


# ---------------------------------------------------------------------------------------


# ================================================================================
# ================================================================================
class FfmpegTools:
    # Konstanten zur Vermeidung von Literalen (Wartbarkeit maximiert)
    """Konstanten zur Vermeidung von Literalen (Wartbarkeit maximiert)"""

    MAJOR_VERSION: int = 4
    _WIN32_PLATFORM: str = "win32"
    _VERSION_ARG: str = "-version"

    # Vorcompilierte Regex-Muster auf Klassenebene
    _VERSION_LINE_REG: re.Pattern[str] = re.compile(
        r'ffmpeg version ([a-zA-Z0-9.-]+)',
        flags=re.IGNORECASE
    )
    _VERSION_VALUES_REG: re.Pattern[str] = re.compile(
        r'(N-)?([a-zA-Z0-9]+)[.-]([a-zA-Z0-9]+)[.-]([a-zA-Z0-9]+)',
        flags=re.IGNORECASE
    )
    Version = namedtuple('Version', ['major', 'medium', 'minor'])

    # -------------------------------------------------------------------------------------------
    def __init__(self, config: FfmpegConfig, verbose: bool = False) -> None:
        """
        Initialisiert die FFmpeg-Werkzeuge und validiert die ausführbaren Pfade.

        :param config: (FfmpegConfig) Das Konfigurationsobjekt mit den CLI-Pfaden.
        :param verbose: (bool) Steuert die Detailtiefe der Konsolenausgaben.
        :raises FileNotFoundError: Wenn ffmpeg oder ffprobe nicht gefunden werden.
        """
        self.ffmpeg: str | None = config.ffmpeg_cmd
        self.ffprobe: str | None = config.ffprobe_cmd
        self.verbose = verbose
        self.use_json_format: bool = False

        # Validierung der Binaries auf Existenz
        if self.ffmpeg is None or not Path(self.ffmpeg).is_file():
            raise FileNotFoundError(self.ffmpeg)
        if self.ffprobe is None or not Path(self.ffprobe).is_file():
            raise FileNotFoundError(self.ffprobe)

        # Version ermitteln und JSON-Kompatibilität prüfen
        self.version = self._get_version() if self.ffmpeg else self.Version(major=0, medium=0, minor=0)

        if self.version.major >= FfmpegTools.MAJOR_VERSION:
            self.use_json_format = True

    # -------------------------------------------------------------------------------------------
    @staticmethod
    def to_int(value: str | None) -> int | None:
        """
        Hilfsmethode zur sicheren Konvertierung in einen Integer.

        :param value: (str | None) Der zu konvertierende String.
        :return: Der konvertierte Integer oder None bei Fehlern/leeren Werten.
        :rtype: int | None
        """
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None

    # -------------------------------------------------------------------------------------------
    @staticmethod
    def run_cmd_raw(cmd, args) -> Result:
        """
        Führt einen nativen System-Befehl abgetrennt im Hintergrund aus.

        Unterdrückt unter Windows-Systemen das Aufpoppen von CMD-Konsolenfenstern
        über die entsprechenden Prozess-Creation-Flags.

        :param cmd: (str) Der Pfad zum auszuführenden Befehl (Binary).
        :param args: (list[str]) Die Argumente, die dem Befehl übergeben werden.
        :return: Das Result-Objekt mit Exit-Code, stdout und dekodiertem stderr.
        :rtype: Result
        """
        # Unterdrücken des Konsolenfensters unter Windows im Konstanten-Vergleich
        creationflags: int = CREATE_NO_WINDOW if sys.platform == FfmpegTools._WIN32_PLATFORM else 0

        result = run(
            [cmd] + args,
            stdout=PIPE,
            stderr=PIPE,
            creationflags=creationflags  # Das Flag hinzufügen
        )

        # stderr wird direkt als utf-8 dekodiert, stdout bleibt raw für Binärdaten/Chunks
        return Result(result.returncode, result.stdout, result.stderr.decode('utf-8'))

    # -------------------------------------------------------------------------------------------
    def call_ffmpeg(self, args: list[str]) -> Result:
        """Ruft das konfigurierte FFmpeg-Binary mit Argumenten auf.

                :param args: (list[str]) CLI-Parameter für FFmpeg.
                :return: Das standardisierte Resultat des Subprozesses.
                :rtype: Result
                """
        return self.run_cmd_raw(self.ffmpeg, args)

    # -------------------------------------------------------------------------------------------
    def call_ffprobe(self, args: list[str]) -> Result:
        """Ruft das konfigurierte FFprobe-Binary mit Argumenten auf.

                :param args: (list[str]) CLI-Parameter für FFprobe.
                :return: Das standardisierte Resultat des Subprozesses.
                :rtype: Result
                """
        return self.run_cmd_raw(self.ffprobe, args)

    # -------------------------------------------------------------------------------------------
    def _get_version(self) -> Version:
        """Ermittelt die installierte FFmpeg-Version über die CLI-Ausgabe.
        
        :return: (Version) Beschreibung des Rückgabewerts.
        """

        major: int = 0
        medium: int = 0
        minor: int = 0

        output = self.call_ffmpeg([FfmpegTools._VERSION_ARG])
        version_info = output.out.decode('utf-8')

        # Versionszeile isolieren
        match_line = self._VERSION_LINE_REG.search(version_info)

        if match_line and len(match_line.groups()) == 1:
            version_data: str = match_line.group(1)

            # Versionsnummer zerlegen
            match_values = self._VERSION_VALUES_REG.search(version_data)
            if match_values:
                raw_major = self.to_int(match_values.group(2))
                raw_medium = self.to_int(match_values.group(3))
                raw_minor = self.to_int(match_values.group(4))

                # Versionen korrigieren und Standard-Fallbacks anwenden
                major = FfmpegTools.MAJOR_VERSION if not raw_major else raw_major
                medium = raw_medium if raw_medium else 0
                minor = raw_minor if raw_minor else 0

        return FfmpegTools.Version(major, medium, minor)


# -------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------
def get_ffmpeg_service(verbose: bool = False) -> FfmpegTools:
    """Gibt die Singleton-Instanz der FfmpegTools zurück.

    Nutzt ein statisches Funktions-Attribut als internen Speicher, um das
    Schlüsselwort 'global' vollständig zu vermeiden.

    :param verbose: (bool) Definiert den Verbose-Status bei der Erstinitialisierung.
    :return: Die einzige Instanz der FfmpegTools-Klasse.
    :rtype: FfmpegTools
    """
    # Prüfen, ob das Attribut bereits auf der Funktion existiert
    if not hasattr(get_ffmpeg_service, "_instance"):
        # Erstinitialisierung
        instance = FfmpegTools(config=FfmpegConfig(), verbose=verbose)
        setattr(get_ffmpeg_service, "_instance", instance)
        return instance

    # Linter weiß hier zu 100%, dass das Attribut existiert und vom Typ FfmpegTools ist
    return getattr(get_ffmpeg_service, "_instance")
