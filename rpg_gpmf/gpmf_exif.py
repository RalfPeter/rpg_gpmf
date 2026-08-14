#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 13-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm           : gpmf_exif.py
#  Version            : 2.3
#  Beschreibung       : Keine Beschreibung verfügbar.
#  Zeilen             : 979
#  Abhängigkeiten     : abc, argparse, bisect, cProfile, collections, configparser, ctypes, dataclasses, datetime, enum
#                       fractions, functools, glob, hashlib, http, inspect, io, json, locale, logging, math, mmap, os
#                       pathlib, pickle, platform, pstats, re, shutil, struct, subprocess, sys, tempfile, textwrap
#                       threading, time, traceback, typing, xml, zipfile, zoneinfo
#  Externe Frameworks : gpxpy, lxml, numpy, overpy, pandas, pyexiv2, requests, scipy, tzlocal, yaml
#  Eigene Frameworks  : rpg_geo, rpg_gpmf, rpg_gpx, rpg_utils
#  Klassen            : EExiv2
# ------------------------------------------------------------------------------

import re
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from shutil import copy2
from pyexiv2 import ImageData, convert_exif_to_xmp, convert_iptc_to_xmp, set_log_level

from rpg_gpmf.gpmf_geo import get_geolocator_service
from rpg_gpmf.gpmf_geo_schema import GeoInfo, GeoNeighbor
from rpg_gpx.gpx_schema import GeoPoint, GeoPointTime
from rpg_utils.utils_core import TRENNER, log_to_callback, CallbackTag as Tag
from rpg_utils.utils_datetime import EXIF_DATE, EXIF_DATETIME, IPTC_DATE, IPTC_TIME, TZ_UTC, DateTimeUtils
from rpg_utils.utils_filepath import ENCODING_ISO, ENCODING_UTF8
from rpg_utils.utils_math import MathUtils
from rpg_utils.utils_string import StringUtils as Str

# --- Konstanten für EXIF, IPTC, XMP ---
ExifDateTimeOriginal = 'Exif.Photo.DateTimeOriginal'
ExifDateTimeDigitized = 'Exif.Photo.DateTimeDigitized'
ExifOffsetTimeOriginal = 'Exif.Photo.OffsetTimeOriginal'
ExifOffsetTime = 'Exif.Photo.OffsetTime'
ExifPhoto882a = 'Exif.Photo.0x882a'
ExifTimezoneOffset = 'Exif.Image.TimeZoneOffset'
ExifArtist = 'Exif.Image.Artist'
ExifGPSLatitude = 'Exif.GPSInfo.GPSLatitude'
ExifGPSLongitude = 'Exif.GPSInfo.GPSLongitude'
ExifGPSAltitude = 'Exif.GPSInfo.GPSAltitude'
ExifGPSLatitudeRef = 'Exif.GPSInfo.GPSLatitudeRef'
ExifGPSLongitudeRef = 'Exif.GPSInfo.GPSLongitudeRef'
ExifGPSAltitudeRef = 'Exif.GPSInfo.GPSAltitudeRef'
ExifGPSMapDatum = 'Exif.GPSInfo.GPSMapDatum'
ExifGPSVersionID = 'Exif.GPSInfo.GPSVersionID'
ExifGPSDateStamp = 'Exif.GPSInfo.GPSDateStamp'
ExifGPSTimeStamp = 'Exif.GPSInfo.GPSTimeStamp'

IPTCCharacterSet = 'Iptc.Envelope.CharacterSet'
IPTCUtf8EscSequence = '\x1b%G'
IPTCDateCreated = 'Iptc.Application2.DateCreated'
IPTCTimeCreated = 'Iptc.Application2.TimeCreated'
IPTCByline = 'Iptc.Application2.Byline'
IPTCCountryCode3 = 'Iptc.Application2.CountryCode'
IPTCCountryName = 'Iptc.Application2.CountryName'
IPTCProvinceState = 'Iptc.Application2.ProvinceState'
IPTCCity = 'Iptc.Application2.City'
IPTCSubLocation = 'Iptc.Application2.SubLocation'
IPTCKeywords = 'Iptc.Application2.Keywords'

XmpByline = 'Xmp.dc.creator'
XmpKeywords = 'Xmp.dc.subject'
XmpCountryCode3 = 'Xmp.iptc.CountryCode'
XmpSubLocation = 'Xmp.iptc.Location'
XmpPhotoshopCreateDate = 'Xmp.photoshop.CreateDate'
XmpPhotoshopDateCreated = 'Xmp.photoshop.DateCreated'
XmpCountryName = 'Xmp.photoshop.Country'
XmpProvinceState = 'Xmp.photoshop.State'
XmpCity = 'Xmp.photoshop.City'
XMPExifDateTimeOriginal = 'Xmp.exif.DateTimeOriginal'
XMPExifDateTimeDigitized = 'Xmp.exif.DateTimeDigitized'
XMPDigikamTagsList = 'Xmp.digiKam.TagsList'
XMPPatternMwgRsName = '.*RegionList.*mwg-rs:Name.*'
XMPPatternMpregName = '.*RegionInfo.*MPReg:PersonDisplayName.*'

# --- Konstanten für die Pfadsegmente ---
PATH_COUNTRIES: str = "Länder"
PATH_PLACES: str = "Orte"
PATH_REGIONS: str = "Region"
PATH_PERSONS: str = "Personen"

# --- Konstanten für Zeitdifferenz ---
MAX_TIME_DRIFT_SECONDS: int = 3600


# ================================================================================
# ================================================================================
class EExiv2:
    """Wrapper-Klasse für pyexiv2 zur vereinfachten Verwaltung und Korrektur von Bildmetadaten."""

    # --------------------------------------------------------------------------------
    def __init__(self, file: str | Path, verbose: bool = False):
        """Initialisiert das EExiv2-Objekt und lädt die Metadaten der Bilddatei.

        :param file: (str | Path) Pfad zur Bilddatei.
        :param verbose: (bool) Steuert, ob detaillierte Debug-Logs ausgegeben werden.
        """
        self.classname: str = self.__class__.__name__

        file = Path(file).resolve()
        if not file.is_file():
            raise ValueError(f"Not a filename {file}")

        self.file = file
        self.name = str(file.name)
        self.path = Path(file.parent)
        self.verbose = verbose
        self.deletetemp = False

        # initialize geonames
        self.geolocator = get_geolocator_service(verbose=verbose)
        self.image: ImageData | None = None

        # initialize image
        try:
            set_log_level(level=4)
            with open(self.file, 'rb') as f:
                try:
                    self.image = ImageData(f.read())
                except UnicodeDecodeError as e:
                    # Übergabe an die log-Funktion
                    self._log_unicode_decode_details(e)
                    raise UnicodeDecodeError from e
                except RuntimeError as e:
                    log_to_callback(Tag.ERR, 'EXIF init', f"Fehler: (Typ: {type(e).__name__}) - {e.args}")
                except Exception as e:
                    log_to_callback(Tag.ERR, 'EXIF init', f"Fehler: (Typ: {type(e).__name__}) - {e.args}")
                    raise

                if self.image:
                    assert self.image is not None
                    # Lese die Exif-Metadaten
                    self.data_exif = self.read_exif()
                    # Lese die IPTC-Metadaten
                    self.data_iptc = self.read_iptc()
                    # Lese die XMP-Metadaten
                    self.data_xmp = self.read_xmp()
                    # Lese den Kommentar
                    self.comment = self._read_comment()
                    # Lese die ICC-Metadaten
                    self.data_icc = self.image.read_icc()
                    # Lese die Thumbnail
                    self.data_thumbnail = self.image.read_thumbnail()
        except TypeError as e:
            log_to_callback(Tag.ERR, 'EXIF init', f"Fehler: {type(e).__name__} - {e.args}")
            raise TypeError from e

    # --------------------------------------------------------------------------------
    def _log_unicode_decode_details(self, e: UnicodeDecodeError, verbose: bool = False):
        """Loggt spezifische Details eines UnicodeDecodeError.

        :param e: (UnicodeDecodeError) Das abgefangene Exception-Objekt.
        :param verbose: (bool) Wenn True, wird der Fehler aktiv in das Log geschrieben.
        """
        error_details = [e.encoding, e.object, e.start, e.end, e.reason]
        # Übergabe an die log-Funktion
        if verbose:
            log_to_callback(Tag.ERR, 'EXIF unicode_decode', f"Fehler im Foto {self.file.name}: Typ: {type(e).__name__}", *error_details)

    # --------------------------------------------------------------------------------
    def _read_metadata_safely(self, method_name: str) -> dict | str:
        """Hilfsmethode, um Metadaten mit einem Fallback von UTF-8 auf ISO-8859-1 zu lesen.

        :param method_name: (str) Name der pyexiv2-Lesemethode.
        :return: (dict | str) Die gelesenen Metadatenstrukturen oder Strings.
        """
        assert self.image is not None
        method = getattr(self.image, method_name)
        try:
            # encoding standard is utf-8, but could be iso-8859-1
            return method(encoding=ENCODING_UTF8)
        except UnicodeDecodeError as e:
            # Übergabe an die log-Funktion
            self._log_unicode_decode_details(e)
            try:
                return method(encoding=ENCODING_ISO)
            except UnicodeDecodeError as err:
                # Übergabe an die log-Funktion
                self._log_unicode_decode_details(err, verbose=True)
                raise UnicodeDecodeError from err

    # --------------------------------------------------------------------------------
    def _read_comment(self) -> str:
        """Liest den Bildkommentar unter Berücksichtigung alternativer Encodings.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        data = self._read_metadata_safely('read_comment')
        assert isinstance(data, str)
        return data

    # --------------------------------------------------------------------------------
    def _read_exif(self) -> dict:
        """Interne Methode zum rohen Auslesen der EXIF-Daten mit Encoding-Fallback.
        
        :return: (dict) Beschreibung des Rückgabewerts.
        """

        data = self._read_metadata_safely('read_exif')
        assert isinstance(data, dict)
        return data

    # --------------------------------------------------------------------------------
    def read_exif(self) -> dict:
        """Liest, korrigiert und normalisiert die EXIF-Metadaten des Bildes.
        
        :return: (dict) Beschreibung des Rückgabewerts.
        """

        data = self._read_exif()

        if self.verbose:
            # Gib alle Metadaten aus
            log_to_callback(Tag.STATUS, 'EExiv2 Exif', "Exif-Metadaten vor Korrektur")
            for key, value in data.items():
                log_to_callback(Tag.STATUS, f"{key}: {value}")

        # Korrekturen
        change_data = {}
        if ExifGPSVersionID in data and isinstance(data[ExifGPSVersionID], list):
            change_data[ExifGPSVersionID] = data[ExifGPSVersionID][-1]

        if ExifGPSAltitudeRef in data and isinstance(data[ExifGPSAltitudeRef], list):
            change_data[ExifGPSAltitudeRef] = data[ExifGPSAltitudeRef][-1]

        if ExifPhoto882a in data:
            tzh = data[ExifPhoto882a]
            change_data[ExifPhoto882a] = None
            if isinstance(tzh, tuple):
                tzh = tzh[0]
            change_data[ExifTimezoneOffset] = tzh

        if ExifGPSMapDatum in data:
            change_data[ExifGPSMapDatum] = None

        if ExifDateTimeOriginal in data:
            dto_raw: str = data[ExifDateTimeOriginal]
            offset_raw: str | None = data.get(ExifOffsetTimeOriginal)

            # 1. Daten berechnen und Tupel entpacken
            dto, offset, d_stamp, t_stamp = DateTimeUtils.prepare_exif_datetime_fields(dto=dto_raw, offset=offset_raw)

            # 2. String-Korrekturen hinzufügen (doppelte Zuweisung, wie im Originalcode)
            change_data[ExifDateTimeOriginal] = dto
            change_data[ExifDateTimeDigitized] = dto
            change_data[ExifOffsetTimeOriginal] = offset
            change_data[ExifOffsetTime] = offset

            # 3. GPS-Ableitungen hinzufügen
            change_data[ExifGPSDateStamp] = d_stamp
            change_data[ExifGPSTimeStamp] = t_stamp

        try:
            if self._update(change_exif=change_data):
                data = self._read_exif()
        except AttributeError as e:
            log_to_callback(Tag.STATUS, 'EXIF init', f"Fehler: {type(e).__name__} - {e.args}")
            raise AttributeError from e

        if self.verbose:
            # Gib alle Metadaten aus
            log_to_callback(Tag.STATUS, TRENNER)
            log_to_callback(Tag.STATUS, 'EExiv2 Exif', "Exif-Metadaten nach Korrektur")
            for key, value in data.items():
                log_to_callback(Tag.STATUS, f"{key}: {value}")
            log_to_callback(Tag.STATUS, TRENNER)

        return data

    # --------------------------------------------------------------------------------
    def _read_iptc(self) -> dict:
        """Interne Methode zum rohen Auslesen der IPTC-Daten mit Encoding-Fallback.
        
        :return: (dict) Beschreibung des Rückgabewerts.
        """

        data = self._read_metadata_safely('read_iptc')
        assert isinstance(data, dict)
        return data

    # --------------------------------------------------------------------------------
    def read_iptc(self) -> dict:
        """Liest, korrigiert und synchronisiert IPTC-Daten basierend auf EXIF-Referenzen.
        
        :return: (dict) Beschreibung des Rückgabewerts.
        """

        data = self._read_iptc()
        change_data = {}

        if self.verbose:
            # Gib alle Metadaten aus
            log_to_callback(Tag.STATUS, "EExiv2 IPTC", "IPTC-Metadaten vor Korrektur")
            for key, value in data.items():
                log_to_callback(Tag.STATUS, f"{key}: {value}")

        # Korrekturen
        if {ExifDateTimeOriginal, ExifOffsetTimeOriginal}.issubset(self.data_exif.keys()):
            dto = self.data_exif.get(ExifDateTimeOriginal)
            offset = self.data_exif.get(ExifOffsetTimeOriginal)
            iptc_date, iptc_time = DateTimeUtils.prepare_iptc_datetime_fields(dto, offset_raw=offset)

            change_data[IPTCDateCreated] = iptc_date
            change_data[IPTCTimeCreated] = iptc_time

            if self._update(change_iptc=change_data):
                data = self._read_iptc()

        if self.verbose:
            # Gib alle Metadaten aus
            log_to_callback(Tag.STATUS, TRENNER)
            log_to_callback(Tag.STATUS, 'EExiv2 IPTC', "IPTC-Metadaten nach Korrektur")
            for key, value in data.items():
                log_to_callback(Tag.STATUS, f"{key}: {value}")
            log_to_callback(Tag.STATUS, TRENNER)

        return data

    # --------------------------------------------------------------------------------
    def _read_xmp(self) -> dict:
        """Interne Methode zum rohen Auslesen der XMP-Daten mit Encoding-Fallback.
        
        :return: (dict) Beschreibung des Rückgabewerts.
        """

        data = self._read_metadata_safely('read_xmp')
        assert isinstance(data, dict)
        return data

    # --------------------------------------------------------------------------------
    def read_xmp(self) -> dict:
        """Liest XMP-Daten aus und loggt bei Bedarf spezifische Region- oder Personentags.
        
        :return: (dict) Beschreibung des Rückgabewerts.
        """

        data = self._read_xmp()
        change_data = {}

        if self.verbose:
            # Gib alle Metadaten aus
            log_to_callback(Tag.STATUS, "EExiv2 XMP", "XMP-Metadaten vor Korrektur")
            for key, value in data.items():
                log_to_callback(Tag.STATUS, f"{key}: {value}")

            # lookup RegionList with person names
            pattern = re.compile('{0}|{1}'.format(XMPPatternMwgRsName, XMPPatternMpregName))
            for key, value in data.items():
                if pattern.match(key):
                    log_to_callback(Tag.STATUS, f"{key}: {value}")

        # Korrekturen
        if self._update(change_xmp=change_data):
            data = self._read_xmp()

        if self.verbose:
            # Gib alle Metadaten aus
            log_to_callback(Tag.STATUS, TRENNER)
            log_to_callback(Tag.STATUS, 'EExiv2 XMP', "XMP-Metadaten nach Korrektur")
            for key, value in data.items():
                log_to_callback(Tag.STATUS, f"{key}: {value}")
            log_to_callback(Tag.STATUS, TRENNER)

        return data

    # --------------------------------------------------------------------------------
    def _from_exif_to_xmp(self):
        """Konvertiert relevante EXIF-Metadatenfelder (inkl. Geodaten) nativ nach XMP."""
        assert self.image is not None
        data = {
            ExifTimezoneOffset: self.data_exif.get(ExifTimezoneOffset),
            ExifGPSVersionID: self.data_exif.get(ExifGPSVersionID),
            ExifGPSLatitude: self.data_exif.get(ExifGPSLatitude),
            ExifGPSLatitudeRef: self.data_exif.get(ExifGPSLatitudeRef),
            ExifGPSLongitude: self.data_exif.get(ExifGPSLongitude),
            ExifGPSLongitudeRef: self.data_exif.get(ExifGPSLongitudeRef),
            ExifGPSAltitude: self.data_exif.get(ExifGPSAltitude),
            ExifGPSAltitudeRef: self.data_exif.get(ExifGPSAltitudeRef),
            ExifGPSDateStamp: self.data_exif.get(ExifGPSDateStamp),
            ExifGPSTimeStamp: self.data_exif.get(ExifGPSTimeStamp)
        }

        # ExifDateTimeOriginal und Offset
        dtd = self.data_exif.get(ExifDateTimeOriginal)
        dtdo = self.data_exif.get(ExifOffsetTimeOriginal)

        if isinstance(dtd, datetime):
            data[ExifDateTimeOriginal] = DateTimeUtils.add_timedelta(dtd, dtdo)

        try:
            # convert exif and iptc to xmp and update the file
            data_new = convert_exif_to_xmp(data)
            self.image.modify_xmp(data_new)
            self.data_xmp = self._read_xmp()
        except AttributeError as e:
            log_to_callback(Tag.STATUS, 'EXIF exif_to_xmp', f"Fehler: {type(e).__name__} - {e.args}")
            raise AttributeError from e
        except RuntimeError as e:
            log_to_callback(Tag.STATUS, 'EXIF exif_to_xmp', f"Fehler: {type(e).__name__} - {e.args}")

    # --------------------------------------------------------------------------------
    def _from_iptc_to_xmp(self):
        """Mappings von IPTC-Feldern nach XMP-Standardstrukturen inkl. Datums-Kompensation."""
        assert self.image is not None
        try:
            # set all needed values to none
            data = {
                XmpPhotoshopCreateDate: None,
                XmpPhotoshopDateCreated: None,
                XmpByline: None,
                XmpCountryCode3: None,
                XmpCountryName: None,
                XmpProvinceState: None,
                XmpCity: None,
                XmpSubLocation: None,
                XmpKeywords: None
            }
            self.image.modify_xmp(data)

            # add new values to xmp
            data = {
                IPTCKeywords: self.data_iptc.get(IPTCKeywords),
                IPTCSubLocation: self.data_iptc.get(IPTCSubLocation),
                IPTCByline: self.data_iptc.get(IPTCByline),
                IPTCCity: self.data_iptc.get(IPTCCity),
                IPTCProvinceState: self.data_iptc.get(IPTCProvinceState),
                IPTCCountryCode3: self.data_iptc.get(IPTCCountryCode3),
                IPTCCountryName: self.data_iptc.get(IPTCCountryName),
                IPTCDateCreated: self.data_iptc.get(IPTCDateCreated),
                IPTCTimeCreated: self.data_iptc.get(IPTCTimeCreated)
            }

            # convert iptc to xmp and update the file
            data_new = convert_iptc_to_xmp(data)

            # ExifDateTimeOriginal und Offset
            dtd = self.data_exif.get(ExifDateTimeOriginal)
            dtdo = self.data_exif.get(ExifOffsetTimeOriginal)
            if dtd:
                data_new[XmpPhotoshopDateCreated] = dtd
                if dtdo:
                    data_new[XmpPhotoshopDateCreated] = DateTimeUtils.add_timedelta(dtd, dtdo)
                data_new[XmpPhotoshopCreateDate] = data_new[XmpPhotoshopDateCreated]

            self.image.modify_xmp(data_new)
            self.data_xmp = self._read_xmp()
        except AttributeError as e:
            log_to_callback(Tag.ERR, 'EXIF iptc_to_xmp', f"Fehler: {type(e).__name__} - {e.args}")
            raise AttributeError from e
        except RuntimeError as e:
            log_to_callback(Tag.ERR, 'EXIF iptc_to_xmp', f"Fehler: {type(e).__name__} - {e.args}")

    # --------------------------------------------------------------------------------
    def _delete_temp(self) -> str | None:
        """Löscht die temporäre Backup-Datei (`~`), falls vorhanden und das Flag gesetzt ist.
        
        :return: (str | None) Beschreibung des Rückgabewerts.
        """

        if self.deletetemp and self.file:
            # Temporäre Datei löschen
            tfile = Path(str(self.file) + '~')
            if tfile.exists():
                tfile.unlink(missing_ok=True)
                return str(tfile.name)
        return None

    # --------------------------------------------------------------------------------
    def _create_temp(self) -> str | None:
        """Erzeugt ein Sicherheitsduplikat (`~`) der aktuellen Datei.
        
        :return: (str | None) Beschreibung des Rückgabewerts.
        """

        if self.file:
            # Temporäre Datei erzeugen
            tfile = Path(str(self.file) + '~')
            try:
                copy2(self.file, tfile)
                if self.verbose:
                    log_to_callback(Tag.STATUS, f"Datei erfolgreich von {self.file.name} nach {tfile.name} dupliziert.")
            except FileNotFoundError:
                log_to_callback(Tag.ERR, f"Fehler: Die Quelldatei {self.file.name} wurde nicht gefunden.")
            except PermissionError:
                log_to_callback(Tag.ERR, "Fehler: Keine Berechtigung, um die Datei zu kopieren oder das Ziel zu überschreiben.")
            except Exception as e:
                log_to_callback(Tag.ERR, f"Ein unerwarteter Fehler ist aufgetreten: {e}")
            return str(tfile.name)
        return None

    # --------------------------------------------------------------------------------
    def _has_exif(self) -> bool | None:
        """Prüft, ob valide EXIF-Datenstrukturen im Bild geladen wurden.
        
        :return: (bool | None) Beschreibung des Rückgabewerts.
        """

        try:
            # Lese die Exif-Daten direkt aus der Bilddatei
            if self.image:
                # Überprüfe, ob der Exif-Schlüssel vorhanden ist
                return self.data_exif is not None
            return None
        except Exception as e:
            log_to_callback(Tag.ERR, f"An error occurred: {type(e).__name__} - {e.args}")
            return False

    # --------------------------------------------------------------------------------
    def _update(self, change_exif: dict | None = None, change_iptc: dict | None = None, change_xmp: dict | None = None) -> bool:
        """Aktualisiert selektiv Metadatenblöcke im Bildobjekt und lädt diese neu.

        :param change_exif: (dict | None) Zu ändernde EXIF-Tags.
        :param change_iptc: (dict | None) Zu ändernde IPTC-Tags.
        :param change_xmp: (dict | None) Zu ändernde XMP-Tags.
        :return: (bool) True, wenn mindestens ein Block modifiziert wurde.
        """
        modified = False
        set_log_level(level=4)
        assert self.image is not None

        try:
            if change_exif and len(change_exif) > 0:
                self.image.modify_exif(change_exif)
                self.data_exif = self._read_exif()
                modified = True
            if change_iptc and len(change_iptc) > 0:
                self.image.modify_iptc(change_iptc)
                self.data_iptc = self._read_iptc()
                modified = True
            if change_xmp and len(change_xmp) > 0:
                self.image.modify_xmp(change_xmp)
                self.data_xmp = self._read_xmp()
                modified = True
        except AttributeError as e:
            log_to_callback(Tag.ERR, 'EXIF_init', f"Fehler: {type(e).__name__} - {e.args}")
            raise AttributeError from e

        set_log_level(level=3)
        return modified

    # --------------------------------------------------------------------------------
    def _save(self, close: bool = True):
        """Synchronisiert XMP, brennt die Bytes zurück in die Datei und räumt Temp-Files auf.

        :param close: (bool) Wenn True, wird die Bildressource danach direkt geschlossen.
        """
        if self.image:
            assert self.image is not None
            try:
                self._from_exif_to_xmp()
                self._from_iptc_to_xmp()
                # Get the bytes data of the image and save it to the file
                data = self.image.get_bytes()
                self._create_temp()
                with open(self.file, 'rb+') as f:
                    # Empty the original file
                    f.seek(0)
                    f.truncate()
                    f.write(data)
            except FileNotFoundError:
                log_to_callback(Tag.ERR, f"File not found: {self.file}")

            if close:
                self.image.close()

        # delete temp file if it exists
        self._delete_temp()

    # --------------------------------------------------------------------------------
    def close(self):
        """Schließt die pyexiv2-Bildressource explizit."""
        if self.image:
            assert self.image is not None
            self.image.close()

    # --------------------------------------------------------------------------------
    def read_creationdate(self, point: GeoPoint | None = None) -> datetime | None:
        """Liest den EXIF-Zeitstempel der ursprünglichen Aufnahme (DateTimeOriginal).

        :param point: (GeoPoint | None) Optionale geografische Koordinaten (Breitengrad/Längengrad)
        :return: (datetime | None) Das zeitzonenbewusste oder naive Erstellungsdatum.
        """

        # --------------------------------------------------------------------------------
        def _get_tzinfo_from_exif_offset(
                offset_original_str: str | None,
                offset_proprietary_str: str | None = None
        ) -> timezone | None:
            """Extrahiert die Zeitzonen-Information aus den EXIF-Offset-Strings und erstellt ein timezone-Objekt.
            
            :param offset_original_str: (str | None) Beschreibung von offset_original_str.
            :param offset_proprietary_str: (str | None) Beschreibung von offset_proprietary_str.
            :return: (timezone | None) Beschreibung des Rückgabewerts.
            """

            offset_str = offset_original_str

            if not offset_str and offset_proprietary_str:
                try:
                    # Nutzung Ihrer Logik für den proprietären Tag: '+0200'
                    # Hier wäre eine Konvertierung ins Zielformat +HHMM nötig, aber
                    # die parse_offset-Methode kann auch +HH:MM direkt verarbeiten.
                    # Wir übergeben den Wert direkt zur zentralen parse_offset-Methode.
                    offset_str = offset_proprietary_str
                except (ValueError, TypeError):
                    return None

            if offset_str:
                try:
                    offset_delta: timedelta = DateTimeUtils().parse_offset(offset_str)
                    return timezone(offset_delta)
                except ValueError:
                    pass
            return None

        if not self.image or not self._has_exif():
            return None

        do_str = self.data_exif.get(ExifDateTimeOriginal)
        if not do_str:
            return None

        # 1. Naives Datum parsen
        try:
            naive_dt = DateTimeUtils().parse_datetime_string(do_str)
            if naive_dt is None:
                return None
        except ValueError:
            return None

        if naive_dt.tzinfo is not None:
            return naive_dt

        # 2. Zeitzone aus EXIF-Offset-Tags bestimmen (Höchste Priorität!)
        tz_info_exif = _get_tzinfo_from_exif_offset(
            offset_original_str=self.data_exif.get(ExifOffsetTimeOriginal),
            offset_proprietary_str=self.data_exif.get(ExifTimezoneOffset)
        )

        if tz_info_exif:
            # Mache das naive Datum mit dem gefundenen EXIF-Offset "aware"
            return naive_dt.replace(tzinfo=tz_info_exif)

        # 3. Zeitzone aus Geopoint bestimmen (Fallback)
        if point is not None and self.geolocator:
            # Annahme: get_tzinfo liefert ein datetime.tzinfo Objekt
            tz_info_geo = self.geolocator.get_tzinfo(latitude=point.latitude, longitude=point.longitude) if self.geolocator else None
            return DateTimeUtils().convert_to_timezone(dt=naive_dt, tz=tz_info_geo)

        # 4. Fallback: Naives Datum zurückgeben
        return naive_dt

    # --------------------------------------------------------------------------------
    def write_exif(self,
                   creation_date: datetime | None = None,
                   creation_author: str | None = None,
                   nearest_point: GeoPointTime | None = None,
                   target_tz: tzinfo | None = None) -> GeoInfo | None:
        """Schreibt EXIF-Metadaten (Datum, Autor, Geolocation) in das Bildobjekt.

        :param creation_date: (datetime | None) Das Erstellungsdatum.
        :param creation_author: (str | None) Der Name des Autors.
        :param nearest_point: (GeoPointTime | None) Der geografische Punkt mit Zeitstempel.
        :param target_tz: (tzinfo | None) Die Ziel-Zeitzone für das Datum.
        :return: (GeoInfo | None) Adressinformationen des Geopunkts oder None.
        """
        if self.image is None:
            return None

        # Geolocation bestimmen, falls nicht übergeben
        if nearest_point is None:
            nearest_point = self.read_geolocation()

        # Erstellungsdatum bestimmen, falls nicht übergeben
        if creation_date is None:
            creation_date = self.read_creationdate(point=nearest_point)

        # Zeitzonen-Konvertierung falls erforderlich
        if creation_date and target_tz and creation_date.tzinfo != target_tz:
            creation_date = DateTimeUtils.convert_to_timezone(creation_date, target_tz)

        # Validierung: Wenn die Zeitdifferenz zu groß ist, gewinnt der GPS-Zeitstempel
        # Wir prüfen explizit auf GeoTimedPoint, um Attribut-Fehler zu vermeiden
        if isinstance(nearest_point, GeoPointTime) and creation_date:
            if nearest_point.timestamp is not None:
                diff = DateTimeUtils.datetime_diff(creation_date, nearest_point.timestamp)
                if diff > MAX_TIME_DRIFT_SECONDS and creation_date.tzinfo:
                    creation_date = DateTimeUtils.convert_to_timezone(nearest_point.timestamp, target_tz)

        # Metadaten schreiben
        tz = target_tz if target_tz else creation_date.tzinfo if creation_date else None
        self._write_creationdate(creation_date=creation_date, creation_author=creation_author, target_tz=tz)

        # GPS-Daten schreiben (Sicherstellen, dass timestamp existiert)
        gps_ts = nearest_point.timestamp if isinstance(nearest_point, GeoPointTime) else None
        gi = self._write_geo_address(point=nearest_point, gps_datestamp=gps_ts)

        self._save(close=True)
        return gi

    # --------------------------------------------------------------------------------
    def _write_creationdate(self, creation_date: datetime | None, creation_author: str | None, target_tz: tzinfo | None) -> bool | None:
        """Die Datumsinformationen werden immer in localtime eingetragen, deshalb erst umrechnen.

        :param creation_date: (datetime | None) Das aufzuspielende Erstellungsdatum.
        :param creation_author: (str | None) Der Name des Autors.
        :param target_tz: (tzinfo | None) Die Ziel-Zeitzone.
        :return: (bool | None) True bei Erfolg, False bei fehlerhaften Eingaben.
        """
        if creation_date is None:
            return False

        # Ändere die EXIF und IPTC-Daten des Bildes
        if self.image:
            if creation_date.tzinfo is None:
                # find the offset, using gps point and datetime
                ot = self.data_exif.get(ExifOffsetTimeOriginal)
                to = self.data_exif.get(ExifTimezoneOffset)

                if ot is None and to is None and self.geolocator:
                    point = self.read_geolocation()
                    if point:
                        tz = self.geolocator.get_tzinfo(latitude=point.latitude, longitude=point.longitude) if self.geolocator else TZ_UTC
                        creation_date = DateTimeUtils.convert_to_timezone(dt=creation_date, tz=tz)
            else:
                # datetime muss mit tz angepasst werden
                creation_date = DateTimeUtils.convert_to_timezone(creation_date, tz=target_tz)

            timezone_string = ''
            timezone_offset_hours = None
            if creation_date:
                # Zeitzonen-Informationen nur einmalig berechnen
                timezone_offset_hours = DateTimeUtils.get_timezone_hour_offset(creation_date) or None
                # Sicherstellen, dass timezone_string immer ein String ist (Fallback auf leeren String)
                timezone_string = DateTimeUtils.convert_to_offset_str(creation_date) or ""

            fdt_exif = DateTimeUtils.format_datetime(dt=creation_date, format_str=EXIF_DATETIME)
            fdt_iptc_date = DateTimeUtils.format_datetime(dt=creation_date, format_str=IPTC_DATE)
            fdt_iptc_time = DateTimeUtils.format_datetime(dt=creation_date, format_str=IPTC_TIME) + timezone_string

            # Speichere aktualisierte Datumsfelder für iptc
            change_data_iptc = {
                IPTCDateCreated: fdt_iptc_date or None,
                IPTCTimeCreated: fdt_iptc_time or None,
                IPTCByline: creation_author or None,
            }

            # Speichere passende Zeitzonen für xmp
            change_data_xmp = {
                XMPExifDateTimeOriginal: fdt_exif + timezone_string or None,
                XMPExifDateTimeDigitized: fdt_exif + timezone_string or None,
            }

            # Speichere passende Zeitzonen für exif
            change_data_exif = {
                ExifDateTimeOriginal: fdt_exif or None,
                ExifDateTimeDigitized: fdt_exif or None,
                ExifTimezoneOffset: timezone_offset_hours or None,
                ExifOffsetTimeOriginal: timezone_string or None,
                ExifOffsetTime: timezone_string or None,
                ExifArtist: creation_author or None,
            }

            if self.verbose:
                log_to_callback(Tag.STATUS, f"CreationDate [{Str.safe_str(creation_date)}] und Author [{Str.safe_str(creation_author)}] gesetzt.")

            self._update(change_exif=change_data_exif, change_iptc=change_data_iptc, change_xmp=change_data_xmp)
            return True
        return None

    # --------------------------------------------------------------------------------
    def read_geolocation(self) -> GeoPoint | None:
        """Extrahiert und konvertiert GPS-Koordinaten aus den EXIF-Tags in ein GeoPoint-Objekt.
        
        :return: (GeoPoint | None) Beschreibung des Rückgabewerts.
        """

        geolocation = None

        if self.image:
            if not self._has_exif():
                return None

            if self.data_exif:
                # 1. Rohdaten extrahieren
                raw_lat = self.data_exif.get(ExifGPSLatitude)
                raw_lon = self.data_exif.get(ExifGPSLongitude)
                # 2. Prüfen, ob es sich um den (0.0, 0.0) handelt
                is_empty = (raw_lat == 0.0 and raw_lon == 0.0)
                # 3. Zuweisung mit String-Konvertierung oder None bei Bug/Fehlen
                lat = Str.safe_str(raw_lat) if (raw_lat is not None and not is_empty) else None
                lon = Str.safe_str(raw_lon) if (raw_lon is not None and not is_empty) else None
                ele = self.data_exif.get(ExifGPSAltitude)
                latr, lonr = self.data_exif.get(ExifGPSLatitudeRef), self.data_exif.get(ExifGPSLongitudeRef)

                try:
                    if lat is not None and lon is not None:
                        # 1. DMS-Strings aufteilen
                        grad_lat, minute_lat, second_lat = lat.split()
                        grad_lon, minute_lon, second_lon = lon.split()

                        # 2. Konvertierung in temporäre Variablen (Typ: float | None)
                        converted_lat = MathUtils.convert_dms_to_dd(
                            MathUtils.rational_to_float(grad_lat),
                            MathUtils.rational_to_float(minute_lat),
                            MathUtils.rational_to_float(second_lat)
                        )
                        converted_lon = MathUtils.convert_dms_to_dd(
                            MathUtils.rational_to_float(grad_lon),
                            MathUtils.rational_to_float(minute_lon),
                            MathUtils.rational_to_float(second_lon)
                        )

                        # 3. Type Narrowing: Explizite Prüfung, ob die Konvertierung erfolgreich war
                        if converted_lat is None or converted_lon is None:
                            raise ValueError("Die DMS-Koordinaten konnten nicht erfolgreich in DD konvertiert werden.")

                        # Ab hier weiß PyCharm zu 100%, dass converted_lat und converted_lon reine 'float'-Typen sind
                        lat = converted_lat
                        lon = converted_lon

                        # 4. Elevation berechnen oder abfragen
                        if not ele:
                            service = self.geolocator
                            if service:
                                ele = service.get_elevation(latitude=lat, longitude=lon)
                        ele = MathUtils.rational_to_float(ele)

                        # Latitude / Longitude Reference
                        latr, lonr = MathUtils.get_geo_ref_multipliers(latr, lonr)
                        geolocation = GeoPoint(latitude=abs(lat) * latr, longitude=abs(lon) * lonr, elevation=ele) if latr and lonr else None

                except AttributeError:
                    geolocation = None

            if self.verbose and geolocation:
                log_to_callback(Tag.STATUS, f'Lat: {Str.safe_str(geolocation.latitude)}, Lon: {Str.safe_str(geolocation.longitude)}, Ele: {Str.safe_str(geolocation.elevation)}')

        return geolocation

    # --------------------------------------------------------------------------------
    def _write_geo_address(self, point: GeoPoint | None, gps_datestamp: datetime | None) -> GeoInfo | None:
        """Schreibt berechnete Geo-Daten und via Geolocator ermittelte Adress-Keywords ins Bild.

        :param point: (GeoPoint | None) Der zu setzende geografische Punkt.
        :param gps_datestamp: (datetime | None) Der zugehörige UTC-Zeitstempel.
        :return: (GeoInfo | None) Strukturierte Ortsinformationen der Geonames-API.
        """
        if self.image is None:
            return None

        # Überprüfen Sie, ob ein GPX-Punkt gefunden wurde
        if point is None:
            if self.verbose:
                log_to_callback(Tag.STATUS, "Kein passender GPX-Punkt gefunden.")
            return None

        # Round the Location data
        latr, lonr = MathUtils.get_geo_refs(lat=point.latitude, lon=point.longitude)
        lat = MathUtils.format_coord_as_rational_dms(point.latitude)
        lon = MathUtils.format_coord_as_rational_dms(point.longitude)

        # get elevation if not present
        ele = point.elevation
        if not ele:
            service = self.geolocator
            if service:
                ele = service.get_elevation(latitude=point.latitude, longitude=point.longitude)
        ele = MathUtils.to_rational_str(ele)
        ref = '0' if ele else None

        # gps date and time
        gps_timestamp = None
        if gps_datestamp:
            gps_datestamp = DateTimeUtils.convert_to_timezone(gps_datestamp, tz=TZ_UTC)
            gps_timestamp = DateTimeUtils.datetime_to_fractions(gps_datestamp)
            gps_datestamp = DateTimeUtils.format_datetime(dt=gps_datestamp, format_str=EXIF_DATE)

        # Speichere das Bild mit den aktualisierten GPS Exif-Tags
        change_data_exif = {
            ExifGPSVersionID: '{} {} {} {}'.format(2, 3, 0, 0),
            ExifGPSLatitude: lat,
            ExifGPSLatitudeRef: latr,
            ExifGPSLongitude: lon,
            ExifGPSLongitudeRef: lonr,
            ExifGPSAltitude: ele,
            ExifGPSAltitudeRef: ref,
            ExifGPSDateStamp: gps_datestamp,
            ExifGPSTimeStamp: gps_timestamp,
        }

        self._update(change_exif=change_data_exif)

        lat_f = MathUtils.safe_float(point.latitude)
        lon_f = MathUtils.safe_float(point.longitude)
        gi = self.geolocator.get_geonames_information(latitude=lat_f, longitude=lon_f) if self.geolocator else None
        if not gi:
            if self.verbose:
                log_to_callback(Tag.STATUS, self.classname, "Keine passende Adresse gefunden.")
            return None

        # Ändere die IPTC-Daten des Bildes
        keywords = self._read_keywords_iptc(gi.neighbor)
        change_data_iptc = {
            IPTCCharacterSet: IPTCUtf8EscSequence,
            IPTCCountryCode3: (gi.neighbor and gi.neighbor.countrycode3) or None,
            IPTCCountryName: (gi.neighbor and gi.neighbor.country) or None,
            IPTCProvinceState: (gi.neighbor and gi.neighbor.state) or None,
            IPTCCity: (gi.neighbor and gi.neighbor.city) or None,
            IPTCSubLocation: (gi.neighbor and gi.neighbor.municipality) or None,
            IPTCKeywords: keywords or None,
        }

        # Digikam Tags: Liste zu String oder spezielles Format für XMP
        digikamtags = self._read_keywords_digikam(gi.neighbor)
        change_data_xmp = {
            XMPDigikamTagsList: digikamtags or None
        }

        self._update(change_iptc=change_data_iptc, change_xmp=change_data_xmp)
        return gi

    # --------------------------------------------------------------------------------
    def _read_keywords_iptc(self, gi: GeoNeighbor | None) -> list | None:
        """Erzeugt eine bereinigte Liste von IPTC-Keywords basierend auf Location- und Personendaten.

        :param gi: (GeoNeighbor | None) Ein GeoAddress-Objekt mit den Geoinformationen.
        :return: (list | None) Liste eindeutiger Schlagwörter für IPTC.
        """
        if gi is None:
            return None

        address_values = [gi.countrycode3, gi.country, gi.state, gi.region, gi.county, gi.city, gi.municipality]
        addresslist = [value for value in address_values if isinstance(value, str) and value]

        personlist = []
        pattern = re.compile(f'{XMPPatternMwgRsName}|{XMPPatternMpregName}')

        for key, value in self.data_xmp.items():
            if pattern.match(key):
                if self.verbose:
                    log_to_callback(Tag.STATUS, self.classname, f"{key}: {value}")
                personlist.append(value)

        final_keywords_set = set()
        for element in addresslist + personlist:
            keyword = Str.decode_bytes(element) if isinstance(element, bytes) else element
            if isinstance(keyword, str) and keyword:
                final_keywords_set.add(keyword)

        return list(final_keywords_set)

    # --------------------------------------------------------------------------------
    def _read_keywords_digikam(self, gi: GeoNeighbor | None) -> list | None:
        """Erzeugt hierarchische, bereinigte Digikam-Tags für Albenstrukturen.

        :param gi: (GeoNeighbor | None) Objekt mit Geoinformationen.
        :return: (list | None) Liste hierarchischer Pfad-Strings für Digikam.
        """
        if gi is None:
            return None

        # 1. Keywords aus Geoinformationen (mit f-Strings und Konstanten)
        countrycode = f"{PATH_COUNTRIES}/{gi.countrycode3}" if gi.countrycode3 else None
        city = f"{PATH_PLACES}/{gi.country}/{gi.city}" if gi.city and gi.country else None
        municipality = f"{PATH_PLACES}/{gi.country}/{gi.municipality}" if gi.municipality and gi.country else None
        state = f"{PATH_REGIONS}/{gi.countrycode2}/{gi.state}" if gi.state and gi.countrycode2 else None

        keywords_list = [countrycode, state, city, municipality]

        # 2. Keywords aus Personen-Metadaten (XMP)
        pattern = re.compile(f'{XMPPatternMwgRsName}|{XMPPatternMpregName}')

        for key, value in self.data_xmp.items():
            if pattern.match(key):
                keywords_list.append(f'{PATH_PERSONS}/{value}')
                if self.verbose:
                    log_to_callback(Tag.STATUS, self.classname, f"{key}: {value}")

        # 3. Bereinigung und Finalisierung der Keywords
        final_keywords_set = set()

        # Effiziente Iteration: Decodierung, Filterung und Duplikatsentfernung in einem Durchlauf
        for element in keywords_list:
            keyword = Str.decode_bytes(element) if isinstance(element, bytes) else element

            # Nur hinzufügen, wenn es ein String und nicht leer ist.
            if isinstance(keyword, str) and keyword:
                final_keywords_set.add(keyword)

        # Rückgabe als list (Kern-Typ)
        return list(final_keywords_set)
