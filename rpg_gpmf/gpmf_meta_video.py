#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 10-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm          : gpmf_meta_video.py
#  Version           : 2.0
#  Beschreibung      : Keine Beschreibung verfügbar.
#  Zeilen            : 1146
#  Abhängigkeiten    : dataclasses, datetime, functools, json, pathlib, re, typing
#  Klassen           : Meta, NoVideoError, NoSRTError, NoMetaError, SRTMetadataAdapter, VideoFile, VideoFiles
#                     SRTExtractor, SRTFiles
# ------------------------------------------------------------------------------
#  Public Methoden:
#    SRTMetadataAdapter                                   → Spezialisierter Adapter zum Parsen moderner DJI SRT-Dateien.
#      is_dji_video(Path)                                 → Prüft anhand der Begleitdatei, ob es sich um ein DJI-Video handelt.
#      find_first_coordinate_in_text(str)                 → Sucht im bereits geladenen Text der SRT-Datei nach dem ersten gültigen Fix.
#      extract_first_valid_coordinate(Path)               → Analysiert die SRT-Datei und liefert das erste echte Koordinatenpaar zurück.
#
#    VideoFile                                            → Liest gmpf Daten aus einer MP4-Video- oder Binärdatei.
#      geocities()                                        → Lazy-Loading Property für den GeoCitiesDB-Singleton-Dienst.
#      model()                                            → Gibt das ermittelte GoPro-Modell zurück.
#      firmware()                                         → Gibt das ermittelte GoPro-Modell zurück.
#      start_time()                                       → Gibt das Erstellungsdatum des Videos zurück.
#      duration()                                         → Gibt das Erstellungsdatum des Videos zurück.
#      size()                                             → Gibt das Erstellungsdatum des Videos zurück.
#      creation()                                         → Gibt das Erstellungsdatum des Videos zurück.
#      gps_datetime()                                     → Gibt die GPS-Zeit (UTC) des Videos zurück.
#      gps_point()                                        → Gibt die GPS-Zeit (UTC) des Videos zurück.
#      gps_latitude()                                     → Gibt die GPS-Zeit (UTC) des Videos zurück.
#      gps_longitude()                                    → Gibt die GPS-Zeit (UTC) des Videos zurück.
#      tz()                                               → Gibt die Zeitzone der Aufnahme zurück.
#      user()                                             → Gibt den zugewiesenen Benutzer zurück.
#      user(str)                                          → Erlaubt das Setzen des Benutzers.
#      rename(str, datetime, str)                         → Benennt die Datei physisch um, sofern der neue Name nicht bereits existiert.
#      thumbnail(int, bool)                               → Erzeugt ein Vorschaubild an einer definierten Position im Video.
#
#    SRTExtractor                                         → Parser zum Transformieren einer DJI SRT-Datei in eine Liste von GPSData-Objekten.
#      geocities()                                        → Lazy-Loading Property für den GeoCitiesDB-Singleton-Dienst.
# ------------------------------------------------------------------------------
#  Copyright (C) 2026 <ralfpeter.bergheim@gmail.com>
# ------------------------------------------------------------------------------

import re
import json
from dataclasses import dataclass
from datetime import time, datetime, timezone, tzinfo, timedelta
from pathlib import Path
from typing import Any, Final
from functools import cached_property

from rpg_utils.utils_core import log_to_callback, CallbackTag as Tag
from rpg_utils.utils_string import StringUtils as Str
from rpg_utils.utils_filepath import PathUtils
from rpg_utils.utils_datetime import ISO_FORMAT_FILENAME_PART, DateTimeUtils

from rpg_gpmf.gpmf_const import DEFAULT_RESULT, DEFAULT_RESULT_3, SUFFIX_JPG, ENCODER_LIST, THUMBNAIL_START_OFFSET_SEC, VIDEO_EXTENSIONS, SUFFIX_SRT
from rpg_gpmf.gpmf_ffmpeg import get_ffmpeg_service, Result
from rpg_gpx.gpx_schema import GeoPointTime, GPXTrackInfo
from rpg_gpmf import gpmf_geo as geoinfo
from rpg_gpmf.gpmf_geo import GeoCitiesDB, get_geocities_service


# ===========================================================================
# Global variables
# ===========================================================================
# Konstanten für Literale (erhöht Wartbarkeit und verhindert Tippfehler in Dictionary-Keys)
KEY_FORMAT: Final[str] = "format"
KEY_TAGS: Final[str] = "tags"
KEY_STREAMS: Final[str] = "streams"
KEY_LOCATION: Final[str] = "location"
KEY_START_TIME: Final[str] = "start_time"
KEY_DURATION: Final[str] = "duration"
KEY_SIZE: Final[str] = "size"
KEY_MAKER: Final[str] = "maker"
KEY_MODEL: Final[str] = "model"
KEY_FIRMWARE: Final[str] = "firmware"
KEY_ENCODER: Final[str] = "encoder"
KEY_CODEC_NAME: Final[str] = "codec_name"
KEY_ORIG_FORMAT: Final[str] = "original_format"
KEY_CREATION_TIME: Final[str] = "creation_time"
KEY_TIMECODE: Final[str] = "timecode"
KEY_WIDTH: Final[str] = "width"
KEY_HEIGHT: Final[str] = "height"

FFPROBE_JSON_ARGS: Final[list[str]] = [
    "-hide_banner", "-print_format", "json",
    "-show_streams", "-show_format"
]
FFMPEG_THUMB_ARGS_PREFIX: Final[list[str]] = [
    "-y", "-hide_banner", "-loglevel", "error", "-nostats"
]

GOPRO_07 = '07'
GOPRO_08 = '08'
GOPRO_09 = '09'
GOPRO_10 = '10'
GOPRO_11 = '11'
GOPRO_12 = '12'
GOPRO_13 = '13'

GOPRO_MAPPING = {
    'HD7': GOPRO_07,
    'HD8': GOPRO_08,
    'HD9': GOPRO_09,
    'H21': GOPRO_10,
    'H22': GOPRO_11,
    'H23': GOPRO_12,
    'H24': GOPRO_13
}

# Reguläre Ausdrücke für das DJI-spezifische Zeilenformat (ohne redundante Escapes)
DJI_KEY_FRAME_CNT: str = "FrameCnt"
DJI_LAT_PATTERN = re.compile(r"\[latitude:\s*([-+]?\d+\.\d+)]")
DJI_LON_PATTERN = re.compile(r"\[longitude:\s*([-+]?\d+\.\d+)]")
DJI_ALT_PATTERN = re.compile(r"abs_alt:\s*([-+]?\d+\.\d+)")
DJI_DT_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})")
# Regex für die Zeitspanne im SRT-Block (z. B. "00:00:07,719 --> 00:00:07,739")
DJI_TIME_PATTERN = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->")
# Einzel-Regexes für die benötigten DJI-Metadaten innerhalb des Fonts
DJI_FRAME_PATTERN: re.Pattern = re.compile(fr"{re.escape(DJI_KEY_FRAME_CNT)}:\s*(\d+)")
DJI_KV_PATTERN: re.Pattern = re.compile(r"\[([^:]+):\s*([^]]+)]")

KEY_SAMSUNG_OFFSET: str = "com.samsung.android.utc_offset"
KEY_ANDROID_VERSION: str = "com.android.version"


# ================================================================================
# ================================================================================
@dataclass(slots=True)
class Meta:
    """Datenklasse / Struktur."""

    code: int = -1
    creation: datetime | None = None
    tz: tzinfo | None = None
    latitude: float | None = None
    longitude: float | None = None
    maker: str = ''
    model: str = ''
    firmware: str = ''
    user: str = ''
    start_time: float | None = None
    duration: float | None = None
    size: int | None = None
    gps_datetime: datetime | None = None
    gps_point: GeoPointTime | None = None


# ================================================================================
# ================================================================================
class NoVideoError(Exception):
    
    # --------------------------------------------------------------------------------
    """--------------------------------------------------------------------------------"""

    def __init__(self, file: Path, message="Die Datei ist kein Video."):
        """Funktionsbeschreibung.
        
        :param file: (Path) Beschreibung
        :param message: (Any) Beschreibung
        """
        self.message = message
        self.file = file
        if file:
            self.path = file.parent
            self.name = file.name
        super().__init__(message)


# ================================================================================
# ================================================================================
class NoSRTError(Exception):
    
    # --------------------------------------------------------------------------------
    """--------------------------------------------------------------------------------"""

    def __init__(self, file: Path, message="Die Datei ist keine SRT-Datei.", reason: str = ""):
        """Funktionsbeschreibung.
        
        :param file: (Path) Beschreibung
        :param message: (Any) Beschreibung
        :param reason: (str) Beschreibung
        """
        self.message: str = f"{message} ({reason})" if reason else message
        self.file = file
        if file:
            self.path = file.parent
            self.name = file.name
        super().__init__(message)


# ================================================================================
# ================================================================================
class NoMetaError(Exception):
    
    # --------------------------------------------------------------------------------
    """--------------------------------------------------------------------------------"""

    def __init__(self, file: Path, message="Die Datei enthält keine Metadaten."):
        """Funktionsbeschreibung.
        
        :param file: (Path) Beschreibung
        :param message: (Any) Beschreibung
        """
        self.message = message
        self.file = file
        if file:
            self.path = file.parent
            self.name = file.name
        super().__init__(message)


# ================================================================================
# ================================================================================
class SRTMetadataAdapter:
    """Spezialisierter Adapter zum Parsen moderner DJI SRT-Dateien."""

    # --------------------------------------------------------------------------------
    @staticmethod
    def is_dji_video(video_path: Path) -> bool:
        """Prüft anhand der Begleitdatei, ob es sich um ein DJI-Video handelt.
        
        :param video_path: (Path) Pfad zur Videodatei.
        :return: (bool) Beschreibung
        """
        return video_path.with_suffix(SUFFIX_SRT.casefold()).is_file()

    # --------------------------------------------------------------------------------
    @classmethod
    def find_first_coordinate_in_text(cls, srt_content: str) -> tuple[float | None, float | None]:
        """Sucht im bereits geladenen Text der SRT-Datei nach dem ersten gültigen Fix.
        
        :param srt_content: (str) Der komplette Inhalt der SRT-Datei.
        :return: (tuple[float | None, float | None]) Beschreibung
        """
        blocks = srt_content.split("\n\n")

        for block in blocks:
            if not block.strip() or "latitude" not in block:
                continue

            lat_match = DJI_LAT_PATTERN.search(block)
            lon_match = DJI_LON_PATTERN.search(block)

            if lat_match and lon_match:
                lat = float(lat_match.group(1))
                lon = float(lon_match.group(1))

                # Null-Insel-Schutz
                if lat == 0.0 and lon == 0.0:
                    continue

                # Validierung des physischen Wertebereichs
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    return lat, lon

        return DEFAULT_RESULT

    # --------------------------------------------------------------------------------
    @classmethod
    def extract_first_valid_coordinate(cls, video_path: Path) -> tuple[float | None, float | None]:
        """Analysiert die SRT-Datei und liefert das erste echte Koordinatenpaar zurück.
        
        :param video_path: (Path) Pfad zur Videodatei.
        :return: (tuple[float | None, float | None]) Beschreibung
        """
        srt_path = video_path.with_suffix(SUFFIX_SRT.casefold())

        if not srt_path.is_file():
            return DEFAULT_RESULT

        # Einmalig öffnen für die Stellen im Code, die nur schnell den ersten Punkt brauchen
        with open(srt_path, "r", encoding="utf-8", errors="ignore") as file:
            content = file.read()

        return cls.find_first_coordinate_in_text(content)


# ================================================================================
# class for video filenaming and reading metadata
# ================================================================================
class VideoFile:
    """Liest gmpf Daten aus einer MP4-Video- oder Binärdatei."""

    # ------------------------------------------------------------------------------------------
    def __init__(self, file: Path | str, verbose: bool = False, use_geocities: bool = True) -> None:
        """Initialisiert die VideoFile Instanz und liest erste Header-Informationen.
        
        :param file: (Path | str) Pfad zur Videodatei.
        :param verbose: (bool) Gibt an, ob detaillierte Logs ausgegeben werden sollen.
        :param use_geocities: (bool | None) Steuert die Geocities-Nutzung für diese Instanz.
                              Bei None greift das globale DEFAULT_GEOCITIES_USE Flag.
        """
        self.verbose = verbose
        # Wenn kein Wert übergeben wurde, greift das globale Flag aus dem gpmf_geo Modul
        self._use_geocities = use_geocities and geoinfo.DEFAULT_GEOCITIES_USE

        self.file = Path(file).resolve()
        if not self.file.is_file():
            raise ValueError(f"Nicht gefunden oder keine Datei: {self.file.name}")

        self.name: str = self.file.name
        self.path: Path = self.file.parent
        self.extension: str = self.file.suffix
        self.basename: str = self._get_basename()

        # ffmpeg instanziieren
        self.ffmtools = get_ffmpeg_service(verbose=verbose)
        self.ffmpeg = self.ffmtools.ffmpeg
        self.ffprobe = self.ffmtools.ffprobe

        self.width: int = 0
        self.height: int = 0

        self.is_dji_video: bool = False

        encoding, encoder = self._read_encoding()
        if encoding:
            self.encoding, self.encoder = self._is_valid_encoding(encoding, encoder, self.name)
        else:
            raise NoVideoError(self.file)

        self._meta_data = self._build_metadata()
        if self._meta_data is None or self._meta_data.code < 0:
            raise NoMetaError(self.file)

    # ------------------------------------------------------------------------------------------
    @cached_property
    def geocities(self) -> GeoCitiesDB | None:
        """Lazy-Loading Property für den GeoCitiesDB-Singleton-Dienst.
        
        :return: (GeoCitiesDB | None) Beschreibung des Rückgabewerts.
        """

        # Wenn Geocities generell oder instanzspezifisch abgeschaltet ist -> Sofort None
        if not self._use_geocities:
            return None

        return get_geocities_service(verbose=self.verbose)

    # ------------------------------------------------------------------------------------------
    @cached_property
    def _rawdata(self) -> dict[str, Any]:
        """Lazy-Loading Property für die Rohdaten der ffprobe JSON-Ausgabe.
        
        :return: (dict[str, Any]) Beschreibung des Rückgabewerts.
        """

        # Early Return löst PyCharms Type-Checker-Problem elegant
        args = FFPROBE_JSON_ARGS + [str(self.file)]
        result = self.ffmtools.call_ffprobe(args)

        if result.code != 0:
            raise RuntimeError(f"ffprobe Fehler bei Datei {self.file}: Code {result.code}")

        return json.loads(result.out)

    # --------------------------------------------------------------------------------
    @property
    def model(self) -> str:
        """Gibt das ermittelte GoPro-Modell zurück.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        return self._meta_data.model if self._meta_data else ""

    # --------------------------------------------------------------------------------
    @property
    def firmware(self) -> str:
        """Gibt das ermittelte GoPro-Modell zurück.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        return self._meta_data.firmware if self._meta_data else ""

    # --------------------------------------------------------------------------------
    @property
    def start_time(self) -> float | None:
        """Gibt das Erstellungsdatum des Videos zurück.
        
        :return: (float | None) Beschreibung des Rückgabewerts.
        """

        return self._meta_data.start_time if self._meta_data else 0.0

    # --------------------------------------------------------------------------------
    @property
    def duration(self) -> float | None:
        """Gibt das Erstellungsdatum des Videos zurück.
        
        :return: (float | None) Beschreibung des Rückgabewerts.
        """

        return self._meta_data.duration if self._meta_data else 0.0

    # --------------------------------------------------------------------------------
    @property
    def size(self) -> int | None:
        """Gibt das Erstellungsdatum des Videos zurück.
        
        :return: (int | None) Beschreibung des Rückgabewerts.
        """

        return self._meta_data.size if self._meta_data else 0

    # --------------------------------------------------------------------------------
    @property
    def creation(self) -> datetime | None:
        """Gibt das Erstellungsdatum des Videos zurück.
        
        :return: (datetime | None) Beschreibung des Rückgabewerts.
        """

        return self._meta_data.creation if self._meta_data else None

    # --------------------------------------------------------------------------------
    @property
    def gps_datetime(self) -> datetime | None:
        """Gibt die GPS-Zeit (UTC) des Videos zurück.
        
        :return: (datetime | None) Beschreibung des Rückgabewerts.
        """

        return self._meta_data.gps_datetime if self._meta_data else None

    # --------------------------------------------------------------------------------
    @property
    def gps_point(self) -> GeoPointTime | None:
        """Gibt die GPS-Zeit (UTC) des Videos zurück.
        
        :return: (GeoPointTime | None) Beschreibung des Rückgabewerts.
        """

        return self._meta_data.gps_point if self._meta_data else None

    # --------------------------------------------------------------------------------
    @property
    def gps_latitude(self) -> float | None:
        """Gibt die GPS-Zeit (UTC) des Videos zurück.
        
        :return: (float | None) Beschreibung des Rückgabewerts.
        """

        return self._meta_data.latitude if self._meta_data else None

    # --------------------------------------------------------------------------------
    @property
    def gps_longitude(self) -> float | None:
        """Gibt die GPS-Zeit (UTC) des Videos zurück.
        
        :return: (float | None) Beschreibung des Rückgabewerts.
        """

        return self._meta_data.longitude if self._meta_data else None

    # --------------------------------------------------------------------------------
    @property
    def tz(self) -> tzinfo | None:
        """Gibt die Zeitzone der Aufnahme zurück.
        
        :return: (tzinfo | None) Beschreibung des Rückgabewerts.
        """

        return self._meta_data.tz if self._meta_data else None

    # --------------------------------------------------------------------------------
    @property
    def user(self) -> str:
        """Gibt den zugewiesenen Benutzer zurück.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        return self._meta_data.user if self._meta_data else ""

    # --------------------------------------------------------------------------------
    @user.setter
    def user(self, value: str) -> None:
        """Erlaubt das Setzen des Benutzers.
        
        :param value: (str) Beschreibung von value.
        :return: (None) Beschreibung des Rückgabewerts.
        """

        if self._meta_data:
            self._meta_data.user = value

    # ------------------------------------------------------------------------------------------
    def _is_valid_encoding(self, encoding: str, encoder: str | None, filename: str) -> tuple[str, str]:
        """Prüft und extrahiert gültige Encoder- und Encoding-Informationen.
        
        :param encoding: (str) Der Encoding-String.
        :param encoder: (str | None) Der Encoder-String.
        :param filename: (str) Name der Datei (für Logging).
        :return: (tuple[str, str]) Beschreibung
        """
        parts = encoding.split()
        teil1 = parts[0] if parts else ""
        teil2 = parts[1] if len(parts) > 1 else (encoder or "")

        if teil1 in ENCODER_LIST:
            return teil2, teil1

        teil1 = teil1 or "Unbekannt"
        teil2 = teil2 or "Unbekannt"

        if self.verbose:
            log_to_callback(Tag.STATUS, "Encoder-Encoding", f"{filename}: Encoder = {teil2}, Encoding = {teil1}")
        return teil1, teil2

    # ------------------------------------------------------------------------------------------
    def _get_basename(self) -> str:
        """Extrahiert den Basisnamen der Datei ohne Zeitstempel-Präfixe.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        match = re.match(r"^\d{8}_\d{6}(.*)$", self.file.stem)
        basename = match.group(1) if match else self.file.stem
        return basename.lstrip("-_#")

    # ------------------------------------------------------------------------------------------
    def _new_filename(self, pattern: str | None = None, dt: datetime | None = None, user: str | None = None) -> Path:
        """Erstellt einen neuen Dateinamen basierend auf einem Muster oder Standardteilen.
        
        :param pattern: (str | None) Optionales Muster für den Dateinamen.
        :param dt: (datetime | None) Optionales datetime-Objekt; andernfalls self.meta.creation.
        :param user: (str | None) Optionaler Benutzername.
        :return: (Path) Beschreibung
        """
        dt_effective = dt or self._meta_data.creation if self._meta_data else None

        if dt_effective is not None:
            dt_local = DateTimeUtils.convert_to_timezone(dt=dt_effective, tz=self._meta_data.tz if self._meta_data else None)
            if dt_local is not None:
                dt_effective = dt_local

        if pattern and dt_effective is not None:
            name = str(Str.replace_placeholders(pattern, dt_effective, self.basename, user))
        else:
            parts = []
            if dt_effective is not None:
                parts.append(f"{dt_effective:{ISO_FORMAT_FILENAME_PART}}")
            if self.basename:
                parts.append(self.basename)
            if user:
                parts.append(user)
            name = "-".join(parts)

        return Path(self.path, name + self.extension)

    # ------------------------------------------------------------------------------------------
    def rename(self, pattern: str | None = None, dt: datetime | None = None, user: str | None = None) -> bool | None:
        """Benennt die Datei physisch um, sofern der neue Name nicht bereits existiert.
        
        :param pattern: (str | None) Optionales Namensmuster.
        :param dt: (datetime | None) Optionaler Zeitstempel.
        :param user: (str | None) Optionaler Benutzername.
        :return: (bool | None) Beschreibung
        """
        if dt is None:
            return None

        dt_effective = dt or self._meta_data.creation if self._meta_data else None
        newfile = self._new_filename(pattern, dt_effective, user)

        # Versuche erst die SRT Datei umzubenennen
        if self.is_dji_video:
            oldsrt = self.file.with_suffix(SUFFIX_SRT.casefold())
            newsrt = newfile.with_suffix(SUFFIX_SRT.casefold())
            if not (oldsrt.name == newsrt.name) and not newsrt.exists():
                if PathUtils.safe_rename(oldsrt, newsrt) and newsrt.is_file():
                    log_to_callback(Tag.STATUS, "UNDO-RENAME", f'"{newsrt}" "{oldsrt}"')

        if newfile.name == self.name:
            return True

        if not newfile.exists():
            if PathUtils.safe_rename(self.file, newfile) and newfile.is_file():
                log_to_callback(Tag.STATUS, "UNDO-RENAME", f'"{newfile}" "{self.file.name}"')
                self.file = newfile
                self.name = newfile.name
                return True

        return False

    # ------------------------------------------------------------------------------------------
    def _read_location(self) -> tuple[float | None, float | None]:
        """Extrahiert die GPS-Koordinaten aus den Format-Tags.
        
        :return: (tuple[float | None, float | None]) Beschreibung des Rückgabewerts.
        """

        # prüfen, ob es eine SRT-Datei gibt und Koordinaten lesen
        # Ausführung der Erkennung
        if SRTMetadataAdapter.is_dji_video(self.path / self.name):
            self.is_dji_video = True
            latitude, longitude = SRTMetadataAdapter.extract_first_valid_coordinate(self.path / self.name)

            if latitude is not None and longitude is not None:
                if self.verbose:
                    log_to_callback(Tag.STATUS, 'DJISrtMetadataAdapter', f"Erfolgreich extrahiert -> Latitude: {latitude}, Longitude: {longitude}")
                return latitude, longitude
            else:
                if self.verbose:
                    log_to_callback(Tag.STATUS, 'DJISrtMetadataAdapter', "Keine gültigen Koordinaten (ungleich 0.0) gefunden.")

        try:
            md = self._rawdata
        except RuntimeError:
            return DEFAULT_RESULT

        info_format = md.get(KEY_FORMAT)
        if isinstance(info_format, dict):
            tags = info_format.get(KEY_TAGS)
            if isinstance(tags, dict):
                loc = tags.get(KEY_LOCATION)
                if isinstance(loc, (str, bytes)):
                    matches = re.findall(r'([+-]?\d+\.\d+)', str(loc))

                    if len(matches) >= 2:
                        try:
                            # Konvertierung direkt beim Auslesen durchführen
                            lat: float = float(matches[0])
                            lon: float = float(matches[1])

                            # Jetzt greift der numerische Vergleich gegen den Kamera-Bug
                            if lat == 0.0 and lon == 0.0:
                                return DEFAULT_RESULT

                            return lat, lon
                        except (ValueError, ArithmeticError):
                            return DEFAULT_RESULT

        return DEFAULT_RESULT

    # ------------------------------------------------------------------------------------------
    @staticmethod
    def _read_model(firmware: str) -> str:
        """Ermittelt das GoPro-Modell anhand der Firmware-Tags aus den Metadaten.
        
        :param firmware: (str) Beschreibung
        :return: (str) Beschreibung
        """
        if not firmware:
            return ''

        return GOPRO_MAPPING.get(firmware[:3], '')

    # ------------------------------------------------------------------------------------------
    def _build_metadata(self) -> Meta | None:
        """Liest grundlegende Metadaten (Dauer, Größe, Maker, Location) aus.
        
        :return: (Meta | None) Beschreibung des Rückgabewerts.
        """

        meta = Meta()
        try:
            md = self._rawdata
        except RuntimeError:
            return DEFAULT_RESULT

        info_format = md.get(KEY_FORMAT, {})
        if info_format:
            start_time_raw = info_format.get(KEY_START_TIME)
            meta.start_time = float(start_time_raw) if start_time_raw is not None else None

            duration_raw = info_format.get(KEY_DURATION)
            meta.duration = float(duration_raw) if duration_raw is not None else None

            size_raw = info_format.get(KEY_SIZE)
            meta.size = int(size_raw) if size_raw is not None else None

            # Fallback auf leere Strings statt None, um Type-Hints der Meta-Klasse zu erfüllen
            meta.maker = str(info_format.get(KEY_MAKER)) if info_format.get(KEY_MAKER) else ""
            meta.model = str(info_format.get(KEY_MODEL)) if info_format.get(KEY_MODEL) else ""

            tags = info_format.get(KEY_TAGS, {})
            meta.firmware = tags.get(KEY_FIRMWARE)
            meta.model = self._read_model(meta.firmware)

            location = self._read_location()
            meta.latitude, meta.longitude = location
            meta.creation, meta.gps_datetime, meta.tz = self._read_creationdate(latitude=meta.latitude, longitude=meta.longitude, model=meta.model)

        meta.code = 1

        if self.verbose:
            log_to_callback(Tag.STATUS, "Metadaten Location", f"Latitude: {Str.safe_str(meta.latitude)}", f"Longitude: {Str.safe_str(meta.longitude)}")

        resolution = self._read_video_resolution(verbose=self.verbose)
        if resolution is not None:
            self.width, self.height = resolution

        return meta

    # ------------------------------------------------------------------------------------------
    def _read_encoding(self) -> tuple[str | None, str | None]:
        """Ermittelt Encoder und Codec-Name aus den Metadaten.
        
        :return: (tuple[str | None, str | None]) Beschreibung des Rückgabewerts.
        """

        encoding, encoder = DEFAULT_RESULT

        try:
            md = self._rawdata
        except RuntimeError:
            return encoding, encoder

        streams = md.get(KEY_STREAMS, [])
        if streams:
            stream = streams[0]
            tags = stream.get(KEY_TAGS, {})
            encoding = tags.get(KEY_ENCODER) or stream.get(KEY_CODEC_NAME)
            encoder = stream.get(KEY_ENCODER) or encoding

        info_format = md.get(KEY_FORMAT, {})
        tags = info_format.get(KEY_TAGS, {})

        if encoder is None:
            encoder = tags.get(KEY_ENCODER) or tags.get(KEY_ORIG_FORMAT)

        return encoding, encoder

    # ------------------------------------------------------------------------------------------
    def _extract_datetime(self, dt: str | None) -> datetime | None:
        """Extrahiert und konvertiert einen Datumsstring basierend auf verschiedenen Formaten.
        
        :param dt: (str | None) Der rohe Datumsstring.
        :return: (datetime | None) Beschreibung
        """
        if dt is None:
            return None

        dt = dt.strip()

        try:
            l_dt = DateTimeUtils.parse_datetime_string(dt)
        except ValueError:
            log_to_callback(Tag.ERR, 'ExtractDateTime', f'Fehler beim Parsen des Datums für den String: {dt}')
            return None

        if l_dt and l_dt.tzinfo is None:
            if self.encoder is None or self.encoder not in ENCODER_LIST:
                l_dt = l_dt.replace(tzinfo=timezone.utc)

        return l_dt

    # --------------------------------------------------------------------------------
    @staticmethod
    def _parse_custom_offset(offset_str: str) -> tzinfo | None:
        """Parst Offsets wie '+0700' oder '-0500' in ein timezone-Objekt.
        
        :param offset_str: (str) Der rohe Offset-String aus den Metadaten.
        :return: (tzinfo | None) Beschreibung
        """
        try:
            # Entfernt eventuelle Leerzeichen
            cleaned = offset_str.strip()
            if len(cleaned) == 5:  # Format +HHMM oder -HHMM
                sign = 1 if cleaned[0] == "+" else -1
                hours = int(cleaned[1:3])
                minutes = int(cleaned[3:5])
                return timezone(timedelta(hours=sign * hours, minutes=sign * minutes))
        except (ValueError, IndexError):
            pass
        return None

    # --------------------------------------------------------------------------------
    @staticmethod
    def _has_real_utc_header(tags: dict[str, Any], model: str = '', has_geo: bool = False) -> bool:
        """Prüft, ob der Video-Header echtes UTC enthält oder ob es sich um.
        
        :param tags: (dict[str, Any]) Format-Tags des Videos.
        :param model: (str) Das bereits aufgelöste Modell (z.B. '09', '11').
        :param has_geo: (bool) True, wenn valide Geodaten für das Video vorliegen.
        :return: (bool) Beschreibung
        """
        # 1. Samsung-Ausnahmen (Sowohl mit Offset als auch mit GPS = Echtes UTC)
        if has_geo:
            return True

        # 2. Standard-Androiden (Lügen beim 'Z', schreiben immer Lokalzeit)
        if "com.android.version" in tags:
            return False

        # 3. GoPro Generationen-Check
        if model:
            return model >= "11"

        # 4. iPhone
        if 'com.apple.quicktime.creationdate' in tags:
            return True

        return False

    # ------------------------------------------------------------------------------------------
    def _read_creationdate(self, latitude: float | None = None, longitude: float | None = None, model: str = '') -> tuple[datetime | None, datetime | None, tzinfo | None]:
        """Liest das Erstellungsdatum aus den Metadaten-Streams oder dem Header aus.
        
        :param latitude: (float | None) Der Breitengrad der Aufnahme.
        :param longitude: (float | None) Der Längengrad der Aufnahme.
        :param model: (str) Beschreibung
        :return: (tuple[datetime | None, datetime | None, tzinfo | None]) Beschreibung
        """
        # 1. Extraktion aus den Tags (wie gehabt)
        stream_creation_time = None

        try:
            md = self._rawdata
        except RuntimeError:
            return DEFAULT_RESULT_3

        streams = md.get(KEY_STREAMS, [])
        if streams:
            tags = streams[0].get(KEY_TAGS, {})
            stream_creation_time = self._extract_datetime(tags.get(KEY_CREATION_TIME))

        header_creation_time = None
        info_format = md.get(KEY_FORMAT, {})
        format_tags = info_format.get(KEY_TAGS, {})
        if info_format:
            header_creation_time = self._extract_datetime(format_tags.get(KEY_CREATION_TIME))

        creation_time = header_creation_time or stream_creation_time
        if creation_time is None:
            return DEFAULT_RESULT_3

        # 2. Zeitzonen-Ermittlung über verschiedene Kanäle
        # Prüfen, ob Geodaten vorhanden sind
        has_geo = None not in (latitude, longitude) and (latitude != 0.0 or longitude != 0.0)
        target_tz: tzinfo | None = None

        # Kanal A: GPS
        if latitude is not None and longitude is not None:
            if (geocities_service := self.geocities) is not None:
                target_tz = geocities_service.get_tzinfo(latitude=latitude, longitude=longitude)

        # Kanal B: Samsung-spezifischer Offset aus dem Header
        samsung_offset_raw = format_tags.get(KEY_SAMSUNG_OFFSET)
        if target_tz is None and samsung_offset_raw:
            has_geo = True
            target_tz = self._parse_custom_offset(str(samsung_offset_raw))

        # 3. Das Dilemma auflösen: Ist die creation_time echtes UTC oder gefälscht?
        if target_tz is not None:
            if self._has_real_utc_header(tags=format_tags, model=model, has_geo=has_geo):
                # FALL 1: Echtes UTC (z.B. GoPro oder dein Samsung-Szenario)
                # Wir RECHNEN die UTC-Zeit sauber in die Zielzeitzone um (+7 Stunden).
                # Aus 06:06:30Z wird 13:06:30+07:00
                gps_time = creation_time
                creation_time = DateTimeUtils.convert_to_timezone(dt=creation_time, tz=target_tz)
            else:
                # FALL 2: Gefälschtes UTC / Reine Lokalzeit im Header (viele andere Androiden/Smartphones)
                # Die Uhrzeit im Header stimmt schon, das 'Z' muss ignoriert/ersetzt werden.
                naive_time = creation_time.replace(tzinfo=None)
                creation_time = naive_time.replace(tzinfo=target_tz)
                gps_time = creation_time
        else:
            # Das Video ist ein Standard-Android/Smartphone ohne GPS.
            # Das 'Z' ist mit an Sicherheit grenzender Wahrscheinlichkeit ein Fake.
            # Ergebnis: Wir geben ein NAIVES datetime-Objekt zurück (ohne tzinfo).
            if not self._has_real_utc_header(tags=format_tags, model=model, has_geo=has_geo):
                creation_time = creation_time.replace(tzinfo=None)
                gps_time = None
            else:
                gps_time = creation_time

        return creation_time, gps_time, creation_time.tzinfo if creation_time else None

    # ------------------------------------------------------------------------------------------
    def _read_video_resolution(self, verbose: bool = False) -> tuple[int, int] | None:
        """Ermittelt die Breite und Höhe des Videos aus dem ersten Stream.
        
        :param verbose: (bool) Steuert detailliertes Logging.
        :return: (tuple[int, int] | None) Beschreibung
        """
        try:
            md = self._rawdata
            stream = md[KEY_STREAMS][0]
        except (IndexError, KeyError, TypeError):
            return 480, 640

        if verbose:
            log_to_callback(Tag.STATUS, 'read_video_resolution', f'output={md}')

        if stream:
            width = stream.get(KEY_WIDTH)
            height = stream.get(KEY_HEIGHT)
            if width is not None and height is not None:
                return int(width), int(height)

        return None

    # ------------------------------------------------------------------------------------------
    def thumbnail(self, delta: int = THUMBNAIL_START_OFFSET_SEC, over: bool = True) -> Path | None:
        """Erzeugt ein Vorschaubild an einer definierten Position im Video.
        
        :param delta: (int) Offset in Sekunden.
        :param over: (bool) Überschreiben erzwingen, falls existent.
        :return: (Path | None) Beschreibung
        """
        thumbfile = self.file.with_suffix(SUFFIX_JPG)

        if not thumbfile.is_file() or over:
            res = self._create_thumbnail(thumbfile, delta)

            if res is not None and res.code == 0:
                log_to_callback(Tag.STATUS, 'Thumbnail erstellen', f'Das Thumbnail {thumbfile.name} wurde erfolgreich erstellt')
                return thumbfile
            else:
                log_to_callback(Tag.ERR, 'Thumbnail erstellen', f'Thumbnail {thumbfile.name} konnte nicht erstellt werden.')
                return None

        return None

    # ------------------------------------------------------------------------------------------
    def _create_thumbnail(self, fnamethumb: Path, position: int, verbose: bool = False) -> Result | None:
        """Ruft ffmpeg auf, um ein einzelnes Frame als Thumbnail zu extrahieren.
        
        :param fnamethumb: (Path) Zielpfad für das Bild.
        :param position: (int) Zeitliche Position im Video in Sekunden.
        :param verbose: (bool) Detailliertes Logging.
        :return: (Result | None) Beschreibung
        """
        try:
            timestamp = time(0, 0, int(position), 0).isoformat()

            args = FFMPEG_THUMB_ARGS_PREFIX + [
                "-ss", timestamp, "-i", str(self.file),
                "-frames:v", "1", str(fnamethumb)
            ]

            if verbose:
                log_to_callback(Tag.STATUS, "ffmpeg", f"Starte Thumbnail-Erzeugung bei {timestamp}")

            res_ffmpeg = self.ffmtools.call_ffmpeg(args)

            if verbose:
                log_to_callback(Tag.STATUS, "ffmpeg extract thumbnail", f'{res_ffmpeg.code} - {res_ffmpeg.out}')

            if fnamethumb.is_file():
                res = Result(0, 'Thumbnail created', '')
            else:
                res = Result(9, '', 'No thumbnail file created')

            return res

        except Exception as e:
            errmsg = f'Fehler bei Thumbnail-Erstellung: {type(e).__name__} - {e}'
            res = Result(99, '', errmsg)
            if verbose:
                log_to_callback(Tag.ERR, "ffmpeg error", errmsg + ' - ' + str(res))
            return res

        finally:
            if verbose:
                log_to_callback(Tag.STATUS, "ffmpeg", f"Thumbnail-Erzeugung abgeschlossen für {self.file.name}")


# ================================================================================
# find all potential video files
# ================================================================================
class VideoFiles:

    # --------------------------------------------------------------------------------
    """--------------------------------------------------------------------------------"""

    def __init__(self, filepath: Path) -> None:
        """Initialisiert das VideoFiles-Objekt und scannt das Verzeichnis.
        
        :param filepath: (Path) Der Pfad zum Verzeichnis, das durchsucht werden soll.
        """
        resolved_path = filepath.resolve()

        # Wenn es eine Datei ist, extrahieren wir das übergeordnete Verzeichnis (.parent)
        if resolved_path.is_file():
            resolved_path = resolved_path.parent
        elif not resolved_path.is_dir():
            raise ValueError(f"Not a valid path: {resolved_path}")

        self.path: Path = resolved_path
        self.files: list[Path] = self._find_video_files()

    # -------------------------------------------------------------------------------------------
    def _find_video_files(self) -> list[Path]:
        """Findet alle Videodateien im gesetzten Verzeichnis durch einen einzigen Scan.
        
        :return: (list[Path]) Beschreibung des Rückgabewerts.
        """

        # 1. Einmaliger, effizienter Scan des Verzeichnisses über self.path
        found_videos = [
            f for f in self.path.iterdir()
            if f.is_file() and f.name.casefold().endswith(VIDEO_EXTENSIONS)
        ]

        # 2. Sortierung der Path-Objekte (sortiert standardmäßig nach dem Pfadnamen)
        found_videos.sort()

        return found_videos


# ================================================================================
# Zentrale Basisklasse Extrahieren von SRT-Daten.
# ================================================================================
class SRTExtractor:
    """Parser zum Transformieren einer DJI SRT-Datei in eine Liste von GPSData-Objekten."""

    # --------------------------------------------------------------------------------
    def __init__(self, file: Path | str, verbose: bool = False) -> None:
        """Initialisiert den Parser mit einem optionalen Dateinamen-Kontext.
        
        :param file: (Path | str) Der Name der Quelldatei für GeoPointRef.
        :param verbose: (bool) Detail-Logging.
        """
        # 1. Datei-Infrastruktur vorbereiten
        self.file: Path = Path(file).resolve()
        self.name: str = self.file.name
        self.extension: str = self.file.suffix.casefold()

        if not (self.file.exists() and self.file.is_file()):
            raise ValueError(f"Nicht gefunden oder keine Datei: {self.name}")

        if self.extension != SUFFIX_SRT.casefold():
            raise NoSRTError(self.file, reason=f"Falsche Extension: {self.extension}")

        self.verbose: bool = verbose

        # erster korrekter GPS Punkt
        # 1. Text sichern (entweder übergeben oder frisch einlesen)
        with open(self.file, "r", encoding="utf-8", errors="ignore") as f:
            self._raw_content = f.read()

        lat, lon = SRTMetadataAdapter.find_first_coordinate_in_text(self._raw_content)
        if lat is not None and lon is not None:
            if (geocities_service := self.geocities) is not None:
                self.timezone = geocities_service.get_tzinfo(latitude=lat, longitude=lon)
        else:
            self.timezone = None

        # Erst jetzt die gesamte Datei in einem Rutsch parsen
        self.trackinfo: GPXTrackInfo = self._parse_to_track_info()
        self.gps_anzitems: int = len(self.trackinfo.points)

    # ------------------------------------------------------------------------------------------
    @cached_property
    def geocities(self) -> GeoCitiesDB | None:
        """Lazy-Loading Property für den GeoCitiesDB-Singleton-Dienst.
        
        :return: (GeoCitiesDB | None) Beschreibung des Rückgabewerts.
        """

        return get_geocities_service(verbose=self.verbose)

    # --------------------------------------------------------------------------------
    def _parse_to_track_info(self) -> GPXTrackInfo:
        """Liest eine DJI .srt Datei und baut ein GPXTrackInfo-Objekt auf.
        
        :return: (GPXTrackInfo) Beschreibung des Rückgabewerts.
        """

        track_points: list[GeoPointTime] = []
        start_time: datetime | None = None
        end_time: datetime | None = None

        if self.file is None or not self.file.is_file():
            return GPXTrackInfo(points=track_points, start_time=start_time)

        # Datei blockweise einlesen (Blöcke sind durch Leerzeilen getrennt)
        with open(self.file, "r", encoding="utf-8", errors="ignore") as file:
            content: str = file.read()
            blocks: list[str] = content.split("\n\n")

        for block in blocks:
            if not block.strip() or "latitude" not in block:
                continue

            lat_match = DJI_LAT_PATTERN.search(block)
            lon_match = DJI_LON_PATTERN.search(block)

            if not lat_match or not lon_match:
                continue

            lat = float(lat_match.group(1))
            lon = float(lon_match.group(1))

            # Ignoriere Einträge vor dem ersten gültigen GPS-Fix (Null-Insel-Schutz)
            if lat == 0.0 and lon == 0.0:
                continue

            # Weiter Metadaten aus dem aktuellen Block extrahieren
            # Elevation
            alt_match = DJI_ALT_PATTERN.search(block)
            elevation = float(alt_match.group(1)) if alt_match else None

            # Zeitstempel des Punktes
            point_datetime = None
            dt_match = DJI_DT_PATTERN.search(block)
            if dt_match:
                try:
                    point_datetime = datetime.strptime(dt_match.group(1), "%Y-%m-%d %H:%M:%S.%f")
                    point_datetime = DateTimeUtils.convert_to_timezone(dt=point_datetime, tz=self.timezone)
                except ValueError:
                    point_datetime = None

            # weitere Metadaten
            md = self._extract_additional_metadata(block)
            md = json.dumps(md, ensure_ascii=False)

            # Setze die Startzeit des Tracks auf den allerersten validen GPS-Punktzeitstempel
            if start_time is None and point_datetime is not None:
                start_time = point_datetime
            end_time = point_datetime if point_datetime else end_time

            # wir erzeugen GeoPointTime
            point = GeoPointTime(
                latitude=lat,
                longitude=lon,
                elevation=elevation,
                timestamp=point_datetime,
                tz=point_datetime.tzinfo if point_datetime else None,
                desc=md
            )

            track_points.append(point)

        return GPXTrackInfo(points=track_points, start_time=start_time, end_time=end_time)

    # --------------------------------------------------------------------------------
    @staticmethod
    def _extract_additional_metadata(srt_text: str) -> dict[str, str]:
        """Extrahiert alle Key-Value Paare aus den eckigen Klammern des SRT-Textes.
        
        :param srt_text: (str) Der rohe Textinhalt des SRT-Blocks.
        :return: (dict[str, str]) Beschreibung
        """
        matches = DJI_KV_PATTERN.findall(srt_text)
        md: dict[str, str] = {key.strip(): value.strip() for key, value in matches}

        # Optionale Zusatzdaten außerhalb der Klammern extrahieren (z.B. FrameCnt)
        frame_match = DJI_FRAME_PATTERN.search(srt_text)
        if frame_match:
            md[DJI_KEY_FRAME_CNT] = frame_match.group(1)

        return md


# ================================================================================
# find all potential gpmf files
# ================================================================================
class SRTFiles:
    
    # --------------------------------------------------------------------------------
    """--------------------------------------------------------------------------------"""

    def __init__(self, filepath: Path):
        """Funktionsbeschreibung.
        
        :param filepath: (Path) Beschreibung
        """
        filepath = filepath.resolve()
        if not filepath.is_dir():
            raise ValueError(f"Not a valid path {filepath}")
        self.path = filepath
        self.files = self._find_srt_files()

    # -------------------------------------------------------------------------------------------
    def _find_srt_files(self) -> list[Path]:
        """Findet alle GPMF- und BIN-Dateien im Verzeichnis durch einen einzigen Scan.
        
        :return: (list[Path]) Beschreibung des Rückgabewerts.
        """

        # 1. Einmaliger, hocheffizienter Scan des Verzeichnisses
        found_files = [
            f
            for f in self.path.iterdir()
            if f.is_file() and f.name.casefold().endswith(SUFFIX_SRT)
        ]

        # 2. Alphabetisch nach Pfad/Dateiname sortieren
        found_files.sort()

        return found_files
