#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 13-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm           : gpmf_writer.py
#  Version            : 2.0
#  Beschreibung       : Keine Beschreibung verfügbar.
#  Zeilen             : 468
#  Abhängigkeiten     : abc, argparse, bisect, cProfile, collections, configparser, ctypes, dataclasses, datetime, enum
#                       fractions, functools, glob, hashlib, http, inspect, io, json, locale, logging, math, mmap, os
#                       pathlib, pickle, platform, pstats, re, shutil, struct, subprocess, sys, tempfile, textwrap
#                       threading, time, traceback, typing, xml, zipfile, zoneinfo
#  Externe Frameworks : gpxpy, lxml, numpy, overpy, pandas, pyexiv2, requests, scipy, tzlocal, yaml
#  Eigene Frameworks  : rpg_geo, rpg_gpmf, rpg_gpx, rpg_utils
#  Klassen            : FileType, GoProFile2TV, GoProFileWrite
# ------------------------------------------------------------------------------

from __future__ import annotations
import zipfile
from pathlib import Path
from enum import Enum
import tempfile

from rpg_utils.utils_core import log_to_callback, CallbackTag as Tag
from rpg_gpmf.gpmf_const import SUFFIX_GPMF, SUFFIX_GPX, SUFFIX_KML, SUFFIX_JSON, SUFFIX_VIRBGPX, SUFFIX_GPXCSV, SUFFIX_HEXCSV, SUFFIX_GYRCSV, SUFFIX_ACCCSV, SUFFIX_ZIP
from rpg_gpmf.gpmf_ffmpeg import get_ffmpeg_service
from rpg_gpmf.gpmf_klv_schema import KLVItem, GPSData, GYROData, ACCLData
from rpg_gpx.gpx_schema import GPXTrackInfo
from rpg_gpmf.gpmf_gpx_generators import GPXGenerator, KMLGenerator, JSONGenerator, HEXGenerator, GPSCSVGenerator, GyroCSVGenerator, ACCLCSVGenerator, GPXGeneratorTrackinfo


# -------------------------------------------------------------------------------------------
# Konstanten für die Dateitypen
# -------------------------------------------------------------------------------------------
# Diese Konstanten sind zur besseren Wartbarkeit im Original-Code erhalten geblieben
# und werden als Klassenebene verwendet.


# ================================================================================
# ================================================================================
class FileType(str, Enum):
    """Unterstützte Dateitypen für den GoPro-Export."""

    BIN = 'BIN'
    KML = 'KML'
    JSN = 'JSN'
    GPX = 'GPX'
    VIB = 'VIB'
    GPS = 'GPS'
    HEX = 'HEX'
    GYR = 'GYR'
    ACC = 'ACC'
    SRT = 'SRT'


# -------------------------------------------------------------------------------------------
# Klasse für das Schreiben von Dateien aus GoPro-Daten
# -------------------------------------------------------------------------------------------


# ================================================================================
# ================================================================================
class GoProFileWrite:
    """Verwaltet die Dateipfade und schreibt die generierten Inhalte"""

    # -------------------------------------------------------------------------------------------
    def __init__(self, filepath: Path, verbose: bool = False):
        """
        Initialisiert den Dateischreiber.

        :param filepath: Der Basispfad, von dem die Ausgabedateinamen abgeleitet werden.
        :param verbose: Gibt an, ob detaillierte Log-Ausgaben erfolgen sollen.
        """
        self.verbose: bool = verbose
        self.base_name: Path = filepath.resolve()
        # _outfiles ist ein Dictionary von {FILETYPE: Path}
        self._outfiles: dict[str, Path] = self._generate_outfile_names()
        self.classname: str = self.__class__.__name__

    # -------------------------------------------------------------------------------------------
    def _generate_outfile_names(self) -> dict[FileType, Path]:
        """Generiert die Ausgabepfade basierend auf den Dateitypen.
        
        :return: (dict[FileType, Path]) Beschreibung des Rückgabewerts.
        """

        # Beispiel für den sauberen, expliziten Zugriff:
        return {
            FileType.BIN: self.base_name.with_suffix(f"{SUFFIX_GPMF}".lower()),
            FileType.KML: self.base_name.with_suffix(f"{SUFFIX_KML.lower()}"),
            FileType.JSN: self.base_name.with_suffix(f"{SUFFIX_JSON.lower()}"),
            FileType.GPX: self.base_name.with_suffix(f"{SUFFIX_GPX.lower()}"),
            FileType.VIB: self.base_name.with_suffix(f"{SUFFIX_VIRBGPX.lower()}"),
            FileType.GPS: self.base_name.with_suffix(f"{SUFFIX_GPXCSV.lower()}"),
            FileType.HEX: self.base_name.with_suffix(f"{SUFFIX_HEXCSV.lower()}"),
            FileType.GYR: self.base_name.with_suffix(f"{SUFFIX_GYRCSV.lower()}"),
            FileType.ACC: self.base_name.with_suffix(f"{SUFFIX_ACCCSV.lower()}"),
            FileType.SRT: self.base_name.with_suffix(f"{SUFFIX_GPX.lower()}"),
        }

    # -------------------------------------------------------------------------------------------
    @staticmethod
    def _write_textfile(filepath: Path | str, text: str) -> None:
        """
        Schreibt einen String in eine Datei mit UTF-8-Kodierung.

        :param filepath: Pfad zum Schreiben der Datei.
        :param text: Der zu schreibende String.
        """
        # F-String-Formatierung für den Dateinamen
        with open(filepath, "wt", encoding='utf-8') as fd:
            fd.write(text)

    # -------------------------------------------------------------------------------------------
    @staticmethod
    def _write_binaryfile(filepath: Path | str, data: bytes) -> None:
        """
        Schreibt einen Bytestream in eine Datei.

        :param filepath: Pfad zum Schreiben der Datei.
        :param data: Die zu schreibenden Bytes.
        """
        # F-String-Formatierung für den Dateinamen
        with open(filepath, "wb") as fd:
            fd.write(data)

    # -------------------------------------------------------------------------------------------
    # --- Dedizierte Schreibmethoden für jede Datei ---
    def write_bin(self, data: bytes | None) -> None:
        """Schreibt die rohen Binärdaten.
        
        :param data: (bytes | None) Beschreibung von data.
        :return: (None) Beschreibung des Rückgabewerts.
        """

        if data is None:
            return
        outfile = self._outfiles[FileType.BIN]
        log_to_callback(Tag.STATUS, self.classname, f"Schreibe Binärdatei: {outfile.name}")
        self._write_binaryfile(outfile, data)

    # --------------------------------------------------------------------------------
    def write_hex(self, klvlist: list[KLVItem]) -> None:
        """Generiert und schreibt die Hex-Ansicht der KLV-Daten.
        
        :param klvlist: (list[KLVItem]) Beschreibung von klvlist.
        :return: (None) Beschreibung des Rückgabewerts.
        """

        outfile = self._outfiles[FileType.HEX]
        log_to_callback(Tag.STATUS, self.classname, f"Schreibe Hex-Datei: {outfile.name}")
        generator = HEXGenerator(data=klvlist, verbose=self.verbose)
        content = generator.generate()
        self._write_textfile(outfile, content)

    # --------------------------------------------------------------------------------
    def write_kml(self, points: list[GPSData]) -> None:
        """Generiert und schreibt die KML-Datei.
        
        :param points: (list[GPSData]) Beschreibung von points.
        :return: (None) Beschreibung des Rückgabewerts.
        """

        outfile = self._outfiles[FileType.KML]
        log_to_callback(Tag.STATUS, self.classname, f"Schreibe KML-Datei: {outfile.name}")
        generator = KMLGenerator(data=points, verbose=self.verbose)
        content = generator.generate()
        self._write_textfile(outfile, content)

    # --------------------------------------------------------------------------------
    def write_gpx(self, points: list[GPSData], locked: bool = False) -> Path:
        """Generiert und schreibt die Standard-GPX-Datei.
        
        :param points: (list[GPSData]) Beschreibung von points.
        :param locked: (bool) Beschreibung von locked.
        :return: (Path) Beschreibung des Rückgabewerts.
        """

        outfile = self._outfiles[FileType.GPX]
        log_to_callback(Tag.STATUS, self.classname, f"Schreibe GPX-Datei: {outfile.name}")
        track_name = f'Created from: [{self.base_name.name}]'
        generator = GPXGenerator(data=points, trackname=track_name, is_locked=locked, verbose=self.verbose)
        content = generator.generate()
        self._write_textfile(outfile, content)
        return outfile

    # --------------------------------------------------------------------------------
    def write_gpx_temp(self, points: list[GPSData], locked: bool = False) -> Path:
        """Generiert und schreibt eine temporäre GPX-Datei.
        
        :param points: (list[GPSData]) Beschreibung von points.
        :param locked: (bool) Beschreibung von locked.
        :return: (Path) Beschreibung des Rückgabewerts.
        """

        # Verwendung von tempfile.NamedTemporaryFile mit Path-Objekt für robusten Code
        # Der Original-Code nutzte tempfile.mktemp, was laut Doku unsicher ist.
        # tempfile.mkstemp wird hier verwendet, um eine gesicherte temporäre Datei zu erstellen.

        # WICHTIG: Die ursprüngliche Logik *schreibt* sofort und gibt dann den Pfad zurück.
        # mkstemp gibt einen Filedescriptor und den Pfad zurück. Wir schließen den FD sofort.
        import os
        fd, temp_path_str = tempfile.mkstemp(suffix=".gpx")
        os.close(fd)  # Filedeskriptor sofort schließen, da wir nur den Pfad brauchen

        temp_outfile = Path(temp_path_str)
        log_to_callback(Tag.STATUS, self.classname, f"Schreibe temporäre GPX-Datei: {temp_outfile.name}")
        track_name = f'Created from: [{self.base_name.name}]'
        generator = GPXGenerator(data=points, trackname=track_name, is_locked=locked, verbose=self.verbose)
        content = generator.generate()
        self._write_textfile(temp_outfile, content)
        return temp_outfile

    # --------------------------------------------------------------------------------
    def write_virb(self, points: list[GPSData], locked: bool = False) -> None:
        """Generiert und schreibt die VIRB-kompatible GPX-Datei.
        
        :param points: (list[GPSData]) Beschreibung von points.
        :param locked: (bool) Beschreibung von locked.
        :return: (None) Beschreibung des Rückgabewerts.
        """

        outfile = self._outfiles[FileType.VIB]
        log_to_callback(Tag.STATUS, self.classname, f"Schreibe VIRB-GPX-Datei: {outfile.name}")
        track_name = f'Created from: [{self.base_name.name}]'
        generator = GPXGenerator(data=points, trackname=track_name, is_locked=locked, verbose=self.verbose)
        content = generator.generate_virb()
        self._write_textfile(outfile, content)

    # --------------------------------------------------------------------------------
    def write_srt(self, points: GPXTrackInfo, locked: bool = False) -> Path:
        """Generiert und schreibt die VIRB-kompatible GPX-Datei.
        
        :param points: (GPXTrackInfo) Beschreibung von points.
        :param locked: (bool) Beschreibung von locked.
        :return: (Path) Beschreibung des Rückgabewerts.
        """

        outfile = self._outfiles[FileType.SRT]
        log_to_callback(Tag.STATUS, self.classname, f"Schreibe SRT-GPX-Datei: {outfile.name}")
        track_name = f'Created from: [{self.base_name.name}]'
        generator = GPXGeneratorTrackinfo(data=points, trackname=track_name, is_locked=locked, verbose=self.verbose)
        content = generator.generate()
        self._write_textfile(outfile, content)
        return outfile

    # --------------------------------------------------------------------------------
    def write_csv_gyro(self, points: list[GYROData]) -> None:
        """Generiert und schreibt die Gyroskop-CSV-Datei.
        
        :param points: (list[GYROData]) Beschreibung von points.
        :return: (None) Beschreibung des Rückgabewerts.
        """

        outfile = self._outfiles[FileType.GYR]
        log_to_callback(Tag.STATUS, self.classname, f"Schreibe Gyro-CSV-Datei: {outfile.name}")
        generator = GyroCSVGenerator(data=points, verbose=self.verbose)
        content = generator.generate()
        self._write_textfile(outfile, content)

    # --------------------------------------------------------------------------------
    def write_csv_accl(self, points: list[ACCLData]) -> None:
        """Generiert und schreibt die Beschleunigungssensor-CSV-Datei.
        
        :param points: (list[ACCLData]) Beschreibung von points.
        :return: (None) Beschreibung des Rückgabewerts.
        """

        outfile = self._outfiles[FileType.ACC]
        log_to_callback(Tag.STATUS, self.classname, f"Schreibe ACCL-CSV-Datei: {outfile.name}")
        generator = ACCLCSVGenerator(data=points, verbose=self.verbose)
        content = generator.generate()
        self._write_textfile(outfile, content)

    # --------------------------------------------------------------------------------
    def write_csv_gps(self, points: list[GPSData]) -> None:
        """Generiert und schreibt die GPS-CSV-Datei.
        
        :param points: (list[GPSData]) Beschreibung von points.
        :return: (None) Beschreibung des Rückgabewerts.
        """

        outfile = self._outfiles[FileType.GPS]
        log_to_callback(Tag.STATUS, self.classname, f"Schreibe GPS-CSV-Datei: {outfile.name}")
        generator = GPSCSVGenerator(data=points, verbose=self.verbose)
        content = generator.generate()
        self._write_textfile(outfile, content)

    # --------------------------------------------------------------------------------
    def write_json(self, klvlist: list[KLVItem]) -> None:
        """Generiert und schreibt die JSON-Datei.
        
        :param klvlist: (list[KLVItem]) Beschreibung von klvlist.
        :return: (None) Beschreibung des Rückgabewerts.
        """

        outfile = self._outfiles[FileType.JSN]
        log_to_callback(Tag.STATUS, self.classname, f"Schreibe JSON-Datei: {outfile.name}")
        generator = JSONGenerator(data=klvlist, verbose=self.verbose)
        content = generator.generate()
        self._write_textfile(outfile, content)

    # -------------------------------------------------------------------------------------------
    def write_zip(self, remove: bool = True) -> Path:
        """
        Erstellt ein ZIP-Archiv aller zuvor generierten Dateien.

        :param remove: Wenn True, werden die Originaldateien nach dem Zippen gelöscht.
        :return: Der Pfad zum erstellten ZIP-Archiv.
        """
        zip_outfile: Path = self.base_name.with_suffix(SUFFIX_ZIP)
        # Existierendes ZIP-File löschen
        zip_outfile.unlink(missing_ok=True)

        with zipfile.ZipFile(zip_outfile, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for l_file_path in self._outfiles.values():
                if not l_file_path.exists():
                    continue
                try:
                    # zip_file.write schreibt die Datei in das Archiv
                    zip_file.write(l_file_path, l_file_path.name)
                    # Optional: Originaldatei entfernen
                    if remove:
                        l_file_path.unlink(missing_ok=True)
                except FileNotFoundError:
                    # Sollte nicht passieren, aber zur Sicherheit
                    log_to_callback(Tag.ERR, f'Fehler beim Zippen: Datei nicht gefunden: {l_file_path.name}')
                    continue
        return zip_outfile


# -------------------------------------------------------------------------------------------
# Klasse für die TV-Konvertierung von GoPro-Videos
# -------------------------------------------------------------------------------------------


# ================================================================================
# ================================================================================
class GoProFile2TV:
    """Konvertiert GoPro-Videos für TV-Wiedergabe via HEVC NVENC."""

    DIR_ORIGINAL: str = "Original"
    SUFFIX_TV:    str = "_tv"

    # --------------------------------------------------------------------------------
    def __init__(self, filepath: Path, cq: int = 20, verbose: bool = False):
        """
        Initialisiert den TV-Konverter.

        :param filepath: Pfad zur GoPro-Quelldatei (.MP4).
        :param cq:       Qualitätsstufe für NVENC (18=besser/größer, 23=kleiner, Standard: 20).
        :param verbose:  Gibt an, ob detaillierte Log-Ausgaben erfolgen sollen.
        """
        self.source:   Path = filepath.resolve()
        self.cq:       int  = cq
        self.verbose:  bool = verbose
        self.output:   Path = self._build_output_path()
        self.original: Path = self.source.parent / self.DIR_ORIGINAL / self.source.name

    # -------------------------------------------------------------------------------------------
    def _build_output_path(self) -> Path:
        """Leitet den Ausgabepfad aus dem Quellpfad ab (<stem>_tv<suffix>).
        
        :return: (Path) Beschreibung des Rückgabewerts.
        """

        stem = self.source.stem + self.SUFFIX_TV
        return self.source.with_name(stem + self.source.suffix)

    # -------------------------------------------------------------------------------------------
    def is_gopro(self) -> bool:
        """Prüft anhand der ffprobe-Metadaten, ob es sich um ein GoPro-Video handelt.
        
        :return: (bool) Beschreibung des Rückgabewerts.
        """

        ffmpeg = get_ffmpeg_service()

        for entry in ("encoder", "handler_name"):
            result = ffmpeg.call_ffprobe([
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", f"stream_tags={entry}",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(self.source),
            ])
            if result.code == 0 and "gopro" in result.out.decode("utf-8").lower():
                log_to_callback(Tag.STATUS, f"GoPro erkannt via {entry}: {self.source.name}")
                return True

        return False

    # -------------------------------------------------------------------------------------------
    def convert(self) -> bool:
        """Konvertiert das GoPro-Video für TV-Wiedergabe.
        
        :return: (bool) Beschreibung des Rückgabewerts.
        """

        ffmpeg = get_ffmpeg_service()

        log_to_callback(Tag.STATUS, f"Konvertiere: {self.source.name} → {self.output.name}")

        result = ffmpeg.call_ffmpeg([
            "-hwaccel", "cuda",
            "-i", str(self.source),
            "-c:v", "hevc_nvenc",
            "-cq", str(self.cq),
            "-preset", "p7",
            "-tag:v", "hvc1",
            "-color_range", "2",
            "-colorspace", "bt709",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-c:a", "copy",
            str(self.output),
        ])

        if result.code != 0:
            log_to_callback(Tag.ERR, f"Konvertierung fehlgeschlagen: {self.source.name}\n{result.error}")
            return False

        log_to_callback(Tag.STATUS, f"Konvertierung erfolgreich: {self.output.name}")
        return True

    # -------------------------------------------------------------------------------------------
    def move_original(self) -> bool:
        """Verschiebt die Quelldatei in den Unterordner 'Original'.
        
        :return: (bool) Beschreibung des Rückgabewerts.
        """

        self.original.parent.mkdir(exist_ok=True)
        try:
            self.source.rename(self.original)
            log_to_callback(Tag.STATUS, f"Original verschoben: {self.source.name} → {self.DIR_ORIGINAL}/")
            return True
        except OSError as e:
            log_to_callback(Tag.ERR, f"Original konnte nicht verschoben werden: {self.source.name} – {e}")
            return False

    # -------------------------------------------------------------------------------------------
    def run(self) -> bool:
        """Führt den vollständigen Workflow aus:
        
        :return: (bool) Beschreibung des Rückgabewerts.
        """

        if not self.is_gopro():
            log_to_callback(Tag.STATUS, f"Kein GoPro-Video: {self.source.name}")
            return False

        if self.output.exists():
            log_to_callback(Tag.STATUS, f"Ausgabe existiert bereits – übersprungen: {self.output.name}")
            return False

        if not self.convert():
            return False

        return self.move_original()

    # -------------------------------------------------------------------------------------------
    @classmethod
    def process_folder(cls, folder: Path, cq: int = 20, verbose: bool = False) -> tuple[int, int, int]:
        """
        Verarbeitet alle MP4-Dateien in einem Ordner.

        :param folder:  Zu verarbeitender Ordner.
        :param cq:      Qualitätsstufe für die Konvertierung.
        :param verbose: Verbose-Ausgabe für jede Datei.
        :return:        Tupel (konvertiert, übersprungen, fehler).
        """
        converted = skipped = errors = 0

        for mp4 in sorted(folder.glob("*.MP4")):
            converter = cls(mp4, cq=cq, verbose=verbose)
            success = converter.run()
            if success:
                converted += 1
            elif converter.output.exists():
                skipped += 1
            else:
                errors += 1

        return converted, skipped, errors
