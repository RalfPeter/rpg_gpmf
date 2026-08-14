#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 13-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm           : gpmf_gpx_generators.py
#  Version            : 2.0
#  Beschreibung       : Keine Beschreibung verfügbar.
#  Zeilen             : 956
#  Abhängigkeiten     : abc, argparse, bisect, cProfile, collections, configparser, ctypes, dataclasses, datetime, enum
#                       fractions, functools, glob, hashlib, http, inspect, io, json, locale, logging, math, mmap, os
#                       pathlib, pickle, platform, pstats, re, shutil, struct, subprocess, sys, tempfile, textwrap
#                       threading, time, traceback, typing, xml, zipfile, zoneinfo
#  Externe Frameworks : gpxpy, lxml, numpy, overpy, pandas, pyexiv2, requests, scipy, tzlocal, yaml
#  Eigene Frameworks  : rpg_geo, rpg_gpmf, rpg_gpx, rpg_utils
#  Klassen            : ACCLCSVGenerator, BaseGenerator (ABC), GPSCSVGenerator, GPXGenerator, GPXGeneratorTrackinfo
#                       GyroCSVGenerator, HEXGenerator, JSONGenerator, KMLGenerator
# ------------------------------------------------------------------------------

from __future__ import annotations
import locale
from typing import Final, Any, Generic, TypeVar
from xml.etree import ElementTree as ET
from xml.dom import minidom
import json
from abc import ABC, abstractmethod

from rpg_utils.utils_datetime import DateTimeUtils, TZ_UTC, ISO_DATETIME_ZULU
from rpg_utils.utils_string import StringUtils as Str
from rpg_gpx.gpx_schema import GPXTrackInfo
from rpg_gpmf.gpmf_klv_schema import KLVItem, GPSData, GYROData, ACCLData
from rpg_gpmf.gpmf_gpx_const import GPX_HEADER_XMLNS_SHORT, GPX_HEADER_XMLNS, GPX_SCHEMA_LOCATION
from rpg_gpmf.gpmf_gpx_const import DEFAULT_TRACK_DESC, DEFAULT_DOC_NAME, DEFAULT_DOC_DESC, DEFAULT_TRACK_TITLE, DEFAULT_STR, DEFAULT_TYPE
from rpg_gpmf.gpmf_gpx_const import GPX_DEFAULT_TRACK_NAME, GPX_XML_DECLARATION, GPX_TRK_OPEN, GPX_SRC_TAG, GPX_TRKSEG_OPEN, GPX_TRKSEG_CLOSE, GPX_TRK_CLOSE, GPX_GPX_CLOSE
from rpg_gpmf.gpmf_gpx_const import KML_NAMESPACE, KML_STYLE_ID, KML_LINE_COLOR, KML_LINE_WIDTH, KML_POLY_COLOR, KML_COORDS_PREFIX
from rpg_gpmf.gpmf_gpx_const import JSON_INDENT, JSON_KEY_FOUR_CC, JSON_KEY_TYPE, JSON_KEY_SIZE, JSON_KEY_REPEAT, JSON_KEY_DATA, JSON_KEY_RAWB, CSV_NEWLINE


# -----------------------------------------------------------
# Konstanten für die Lokalisierung
# -----------------------------------------------------------
LOCALE_CATEGORY: Final[int] = locale.LC_NUMERIC
C_LOCALE: Final[str] = 'C'

# Konstanten für die XML-Generierung (Beispielhaft extrahiert)
DEFAULT_HR: str = "0"
DEFAULT_CAD: str = "0"

# -----------------------------------------------------------
# -----------------------------------------------------------
# Definition des generischen Typs für die Eingangsdaten
T = TypeVar('T', list[GPSData], GPXTrackInfo, list[KLVItem], list[GYROData], list[ACCLData])


# -----------------------------------------------------------
# Basis Generator Klasse
# -----------------------------------------------------------


# ================================================================================
# ================================================================================
class BaseGenerator(ABC, Generic[T]):
    """Abstrakte Basisklasse für alle Telemetrie- und Inhaltsgeneratoren."""

    # --------------------------------------------------------------------------------
    def __init__(
            self,
            data: T,
            is_locked: bool = False,
            verbose: bool = False
    ) -> None:
        """
        Initialisiert den Basis-Generator mit Daten und Steuerparametern.

        :param data: Die spezifischen Eingangsdaten (z.B. Liste von GPSData oder KLVItem).
        :param is_locked: Flag, ob nur valide/fixierte Datenpunkte genutzt werden sollen.
        :param verbose: Aktiviert erweiterte Konsolenausgaben während der Generierung.
        """
        self.data: T = data
        self.is_locked: bool = is_locked
        self.verbose: bool = verbose

    # --------------------------------------------------------------------------------
    @abstractmethod
    def generate(self) -> str:
        """Abstrakte Methode zur Generierung des Zielformats.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        pass

    # --------------------------------------------------------------------------------
    @staticmethod
    def _safe_decode(b_val: bytes | str, default: str = '') -> str:
        """
        Hilfsfunktion, um Bytes sicher zu dekodieren und zu bereinigen.

        :param b_val: Der zu dekodierende Wert (Bytes oder String).
        :param default: Der Standardwert bei einem leeren String.
        :return: Der dekodierte und bereinigte String.
        """
        if isinstance(b_val, bytes):
            return b_val.decode('latin1', errors="replace").strip('\x00')
        return b_val.strip() if b_val != '' else default

    # --------------------------------------------------------------------------------
    @staticmethod
    def _safe_join(b_val: bytes, default: str = ' ') -> str:
        """
        Hilfsfunktion, um Bytes effizient in einen Hex-String umzuwandeln.

        :param b_val: Das Byte-Objekt.
        :param default: Trennzeichen für die Hex-Werte.
        :return: Der formatierte Hex-String.
        """
        if not b_val:
            return ''
        if len(default) == 1:
            return b_val.hex(default)
        return default.join(format(x, '02x') for x in b_val)


# -----------------------------------------------------------
# GPX Generator Klasse
# -----------------------------------------------------------


# ================================================================================
# ================================================================================
class GPXGenerator(BaseGenerator[list[GPSData]]):
    """
    Kapselt die Logik zur Erstellung von GPX 1.1 Dateien aus GPSData-Punkten.
    """
    
    # --------------------------------------------------------------------------------
    def __init__(
            self,
            data: list[GPSData],
            trackname: str = GPX_DEFAULT_TRACK_NAME,
            is_locked: bool = False,
            verbose: bool = False
    ) -> None:
        """
        Initialisiert den GPX-Generator mit Daten und spezifischen Einstellungen.

        :param data: Liste der GPSData-Objekte, die verarbeitet werden sollen.
        :param trackname: Name der GPX-Strecke.
        :param is_locked: Flag, das steuert, ob nur Punkte mit p.fix > 0 verwendet werden.
        :param verbose: Aktiviert erweiterte Protokollierungsausgaben.
        """
        super().__init__(data, is_locked, verbose)
        self.trackname: str = trackname

    # --------------------------------------------------------------------------------
    def generate(self, filter_no: int | None = None) -> str:
        """Erstellt den vollständigen GPX-Inhalt basierend auf den Instanzdaten.
        
        :param filter_no: (int | None) Beschreibung von filter_no.
        :return: (str) Beschreibung des Rückgabewerts.
        """

        if self.verbose:
            print(f"[GPXGenerator] Verarbeite {len(self.data)} von {len(self.data)} Punkten für Track: '{self.trackname}'.")

        gpx_content: str = (
                self._generate_gpx_header(filter_no=filter_no) +
                self._generate_gpx_body(filter_no=filter_no) +
                self._generate_gpx_footer()
        )
        return gpx_content

    # --------------------------------------------------------------------------------
    def generate_virb(self, filter_no: int = 0) -> str:
        """Erstellt den vollständigen GPX-Inhalt im Garmin VIRB-kompatiblen Format.
        
        :param filter_no: (int) Beschreibung von filter_no.
        :return: (str) Beschreibung des Rückgabewerts.
        """

        if self.verbose:
            print(f"[GPXGenerator] Starte VIRB-Export (filter_no erzwungen auf: {filter_no}).")

        return self.generate(filter_no)

    # --------------------------------------------------------------------------------
    def _get_filtered_points(self, filter_no: int = 0) -> list[GPSData]:
        """Filtert die Datenpunkte basierend auf den Instanzkonfigurationen.
        
        :param filter_no: (int) Beschreibung von filter_no.
        :return: (list[GPSData]) Beschreibung des Rückgabewerts.
        """

        return [
            p for p in self.data
            if isinstance(p, GPSData)
            and (not self.is_locked or p.fix > 0)
            and (p.no == filter_no)
        ]

    # --------------------------------------------------------------------------------
    def _generate_gpx_header(self, filter_no: int | None = None) -> str:
        """Generiert den XML-Header der GPX-Datei.
        
        :param filter_no: (int | None) Beschreibung von filter_no.
        :return: (str) Beschreibung des Rückgabewerts.
        """

        if filter_no is not None:
            header = GPX_HEADER_XMLNS_SHORT
        else:
            header = GPX_HEADER_XMLNS + GPX_SCHEMA_LOCATION

        xml_lines: list[str] = [
            GPX_XML_DECLARATION,
            f'<gpx {"\n".join(header)}>\n',
            GPX_TRK_OPEN,
            f'\t<name>{self.trackname}</name>\n',
            GPX_SRC_TAG
        ]
        return ''.join(xml_lines)

    # --------------------------------------------------------------------------------
    def _generate_gpx_body(self, filter_no: int | None = None) -> str:
        """Generiert den XML-Body mit den Trackpunkten.

        :param filter_no: (int | None) Optionale Filter-Nummer für reduzierte Datenpunkte.
        :return: Der formatierte XML-Body-String.
        """
        if filter_no is not None:
            points: list[GPSData] = self._get_filtered_points(filter_no)
        else:
            points: list[GPSData] = self.data

        pts_lines: list[str] = [GPX_TRKSEG_OPEN]

        for l_point in points:
            if l_point.fix <= 0 and self.is_locked:
                continue

            formatted_time: str = DateTimeUtils.format_datetime(
                dt=l_point.datetime,
                tz=TZ_UTC,
                format_str=ISO_DATETIME_ZULU
            )

            # Bei aktivem Filter werden die Extensions weggelassen (Gekürztes Format)
            include_extensions: bool = filter_no is None

            pts_line = self._generate_gpx_trackpoint_xml(
                lat=l_point.latitude,
                lon=l_point.longitude,
                elevation=l_point.altitude,
                formatted_time=formatted_time,
                point_data=l_point,
                include_extensions=include_extensions
            )
            pts_lines.append(pts_line)

        pts_lines.append(GPX_TRKSEG_CLOSE)
        return "".join(pts_lines)

    # --------------------------------------------------------------------------------
    @staticmethod
    def _generate_gpx_trackpoint_xml(
            lat: float,
            lon: float,
            elevation: float,
            formatted_time: str,
            point_data: GPSData,
            include_extensions: bool = True
    ) -> str:
        """Erstellt einen formatierten GPX-Trackpoint-String mittels ElementTree.

        :param lat: (float) Breitengrad des Punktes.
        :param lon: (float) Längengrad des Punktes.
        :param elevation: (float) Höhe des Punktes.
        :param formatted_time: (str) Bereits formatierter Zeitstempel.
        :param point_data: (GPSData) Das vollständige Datenobjekt für erweiterte Metriken.
        :param include_extensions: (bool) Bestimmt, ob die Erweiterten Metriken generiert werden.
        :return: (str) Der fertig eingerückte XML-String des Trackpoints inklusive Newline.
        """
        # 1. Haupt-Trackpoint Element erstellen
        trkpt = ET.Element("trkpt", lat=str(lat), lon=str(lon))

        # 2. Standard-Kindelemente hinzufügen
        ele = ET.SubElement(trkpt, "ele")
        ele.text = str(elevation)

        time_elem = ET.SubElement(trkpt, "time")
        time_elem.text = formatted_time

        # 3. Erweiterte Metriken (Volles Format)
        if include_extensions:
            extensions = ET.SubElement(trkpt, "extensions")
            tpx = ET.SubElement(extensions, "gpxtpx:TrackPointExtension")

            # Units-String sicher verarbeiten
            units_string: str = (
                ",".join(point_data.units)
                if isinstance(point_data.units, list) and not isinstance(point_data.units, str)
                else Str.safe_str(point_data.units)
            )

            metrics: dict[str, str] = {
                "gpxtpx:hr": DEFAULT_HR,
                "gpxtpx:cad": DEFAULT_CAD,
                "gpxtpx:speed": str(point_data.speed2d),
                "gpxtpx:speed3d": str(point_data.speed3d),
                "gpxtpx:distance": str(point_data.distance),
                "gpxtpx:fix": str(point_data.fix),
                "gpxtpx:days2k": str(point_data.days2k),
                "gpxtpx:secs": str(point_data.secs),
                "gpxtpx:DOP": str(point_data.DOP),
                "gpxtpx:units": units_string,
                "gpxtpx:no": str(point_data.no),
            }

            for tag_name, value in metrics.items():
                metric_elem = ET.SubElement(tpx, tag_name)
                metric_elem.text = value

        # 4. Einrückung für die Lesbarkeit (Kompatibel ab Python 3.9+)
        ET.indent(trkpt, space="\t", level=2)

        # 5. In String umwandeln und Basis-Einrückung für das XML-Fragment hinzufügen
        xml_str = ET.tostring(trkpt, encoding="unicode")
        return f"\t\t{xml_str}\n"

    # --------------------------------------------------------------------------------
    @staticmethod
    def _generate_gpx_footer() -> str:
        """Generiert den schließenden XML-Footer.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        return f"{GPX_TRK_CLOSE}{GPX_GPX_CLOSE}"


# -----------------------------------------------------------
# GPX Generator Klasse from GPXTrackInfo
# -----------------------------------------------------------


# ================================================================================
# ================================================================================
class GPXGeneratorTrackinfo(BaseGenerator[GPXTrackInfo]):
    """Erstellt GPX-Dateien direkt aus einem GPXTrackInfo-Datenobjekt."""
    
    # --------------------------------------------------------------------------------
    def __init__(
        self,
        data: GPXTrackInfo,
        trackname: str = GPX_DEFAULT_TRACK_NAME,
        is_locked: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialisiert den Trackinfo-GPX-Generator.

        :param data: Das GPXTrackInfo-Objekt, das die Punkte enthält.
        :param trackname: Name der GPX-Strecke.
        :param is_locked: Flag, ob Filterungen greifen sollen.
        :param verbose: Aktiviert erweiterte Protokollierungsausgaben.
        """
        super().__init__(data, is_locked, verbose)
        self.trackname: str = trackname

    # --------------------------------------------------------------------------------
    def generate(self) -> str:
        """Erstellt den vollständigen GPX-Inhalt basierend auf den Trackinfo-Daten.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        # Hier greifen wir auf die Punkte innerhalb des GPXTrackInfo-Objekts zu
        if self.verbose:
            print(f"[GPXGeneratorTrackinfo] Generiere GPX aus TrackInfo mit {len(self.data.points)} Punkten.")

        gpx_content: str = (
            self._generate_gpx_header() +
            self._generate_gpx_body() +
            self._generate_gpx_footer()
        )
        return gpx_content

    # --------------------------------------------------------------------------------
    def _generate_gpx_header(self) -> str:
        """Generiert den XML-Header unter Verwendung der globalen GPX-Konstanten.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        # Da Trackinfo standardmäßig das volle Format nutzt:
        header_attrs = GPX_HEADER_XMLNS + GPX_SCHEMA_LOCATION

        xml_lines: list[str] = [
            GPX_XML_DECLARATION,
            f'<gpx {"\n".join(header_attrs)}>\n',
            GPX_TRK_OPEN,
            f'\t<name>{self.trackname}</name>\n',
            GPX_SRC_TAG
        ]
        return ''.join(xml_lines)

    # --------------------------------------------------------------------------------
    def _generate_gpx_body(self) -> str:
        """Generiert den XML-Body aus den Trackinfo-Punkten.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        pts_lines: list[str] = [GPX_TRKSEG_OPEN]

        for l_point in self.data.points:
            formatted_time: str = DateTimeUtils.format_datetime(
                dt=l_point.timestamp,
                tz=TZ_UTC,
                format_str=ISO_DATETIME_ZULU
            )

            pts_line = self._generate_gpx_trackpoint_xml(
                lat=l_point.latitude,
                lon=l_point.longitude,
                elevation=l_point.elevation,
                formatted_time=formatted_time,
                desc_content=l_point.desc
            )

            pts_lines.append(pts_line)

        pts_lines.append(GPX_TRKSEG_CLOSE)
        return ''.join(pts_lines)

    # --------------------------------------------------------------------------------
    @staticmethod
    def _generate_gpx_trackpoint_xml(
            lat: float | None = None,
            lon: float | None = None,
            elevation: float | None = None,
            formatted_time: str | None = None,
            desc_content: str | None = None
    ) -> str:
        """Erstellt einen formatierten GPX-Trackpoint-String mit optionaler Beschreibung.

        :param lat: (float) Breitengrad des Punktes.
        :param lon: (float) Längengrad des Punktes.
        :param elevation: (float) Höhe des Punktes.
        :param formatted_time: (str) Bereits formatierter Zeitstempel.
        :param desc_content: (str | None) Optionaler Beschreibungstext (z.B. JSON oder Text).
        :return: (str) Der fertig eingerückte XML-String des Trackpoints.
        """
        # 1. Haupt-Trackpoint Element erstellen
        trkpt = ET.Element("trkpt", lat=Str.safe_str(lat), lon=Str.safe_str(lon))

        # 2. Standard-Kindelemente hinzufügen
        ele = ET.SubElement(trkpt, "ele")
        ele.text = Str.safe_str(elevation)

        time_elem = ET.SubElement(trkpt, "time")
        time_elem.text = formatted_time

        # 3. Bedingte Hinzufügung der Beschreibung (nur wenn Text vorhanden)
        if desc_content and desc_content.strip():
            desc = ET.SubElement(trkpt, "desc")
            desc.text = desc_content.strip()

        # 4. Extensions-Struktur aufbauen
        extensions = ET.SubElement(trkpt, "extensions")
        tpx = ET.SubElement(extensions, "gpxtpx:TrackPointExtension")

        # Standard-Metriken befüllen
        metrics: dict[str, str] = {
            "gpxtpx:hr": "0",
            "gpxtpx:cad": "0",
            "gpxtpx:speed": "0",
            "gpxtpx:speed3d": "0",
            "gpxtpx:distance": "0"
        }

        for tag_name, value in metrics.items():
            metric_elem = ET.SubElement(tpx, tag_name)
            metric_elem.text = value

        # 5. Einrückung für die Lesbarkeit anpassen (Ab Python 3.9 integriert)
        # Da dies ein einzelnes Fragment ist, rücken wir es passend für die Liste ein
        ET.indent(trkpt, space="\t", level=2)

        # In String umwandeln und ein führendes Tab-Paar für das Root-Element sicherstellen
        xml_str = ET.tostring(trkpt, encoding="unicode")
        return f"\t\t{xml_str}\n"

    # --------------------------------------------------------------------------------
    @staticmethod
    def _generate_gpx_footer() -> str:
        """Generiert den schließenden XML-Footer.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        return f"{GPX_TRK_CLOSE}{GPX_GPX_CLOSE}"


# -----------------------------------------------------------
# KML Generator Klasse
# -----------------------------------------------------------


# ================================================================================
# ================================================================================
class KMLGenerator(BaseGenerator[list[GPSData]]):
    """
    Generiert eine KML-Datei (Keyhole Markup Language) aus einer Liste von GPSData-Objekten.
    """
    
    # --------------------------------------------------------------------------------
    def __init__(
            self,
            data: list[GPSData],
            is_locked: bool = False,
            verbose: bool = False
    ) -> None:
        """
        Initialisiert den KML-Generator mit den GPS-Punkten.

        :param data: Liste von Objekten, die GPSData enthalten.
        :param is_locked: Flag, ob nur valide/fixierte Datenpunkte genutzt werden sollen.
        :param verbose: Aktiviert erweiterte Konsolenausgaben.
        """
        super().__init__(data, is_locked, verbose)

    # --------------------------------------------------------------------------------
    def generate(self) -> str:
        """Generiert den vollständigen KML-Inhalt als formatierten XML-String.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        kml_string: str = ''
        original_locale = locale.getlocale(LOCALE_CATEGORY)

        try:
            # Sicherstellen, dass die C-Locale für die korrekte Dezimalpunkt-Formatierung verwendet wird
            locale.setlocale(LOCALE_CATEGORY, C_LOCALE)

            if self.verbose:
                print(f"[KMLGenerator] Starte KML-Generierung für {len(self.data)} Punkte.")

            # 1. XML-Baum erstellen
            kml_root: ET.Element = self._build_kml_tree()

            # 2. Baum serialisieren und formatieren
            kml_string = self._prettify_xml(kml_root)

        finally:
            # Locale wiederherstellen
            try:
                locale.setlocale(LOCALE_CATEGORY, original_locale)
            except locale.Error:
                locale.setlocale(LOCALE_CATEGORY, '')

        return kml_string

    # --------------------------------------------------------------------------------
    def _build_kml_tree(self) -> ET.Element:
        """Erstellt den ElementTree-Baum für die KML-Datei.
        
        :return: (ET.Element) Beschreibung des Rückgabewerts.
        """

        ET.register_namespace('', KML_NAMESPACE)
        kml_root = ET.Element('kml', xmlns=KML_NAMESPACE)
        document = ET.SubElement(kml_root, 'Document')

        # Name und Beschreibung des Dokuments
        ET.SubElement(document, 'name').text = DEFAULT_DOC_NAME
        ET.SubElement(document, 'description').text = DEFAULT_DOC_DESC

        # Style hinzufügen
        self._add_style(document)

        # Placemark und LineString einrichten
        placemark = ET.SubElement(document, 'Placemark')
        ET.SubElement(placemark, 'name').text = DEFAULT_TRACK_TITLE
        ET.SubElement(placemark, 'description').text = DEFAULT_TRACK_DESC
        ET.SubElement(placemark, 'styleUrl').text = f'#{KML_STYLE_ID}'

        line_string = ET.SubElement(placemark, 'LineString')
        ET.SubElement(line_string, 'extrude').text = '1'
        ET.SubElement(line_string, 'tessellate').text = '1'
        ET.SubElement(line_string, 'altitudeMode').text = 'absolute'

        # Koordinaten-Knoten befüllen
        coordinates_element = ET.SubElement(line_string, 'coordinates')
        coordinates_element.text = self._generate_coordinates_body()

        return kml_root

    # --------------------------------------------------------------------------------
    @staticmethod
    def _add_style(document: ET.Element) -> None:
        """
        Fügt dem KML-Dokument den vordefinierten Stil für Linien und Polygone hinzu.

        :param document: Das übergeordnete ET.Element (Document).
        """
        style = ET.SubElement(document, 'Style', id=KML_STYLE_ID)

        line_style = ET.SubElement(style, 'LineStyle')
        ET.SubElement(line_style, 'color').text = KML_LINE_COLOR
        ET.SubElement(line_style, 'width').text = KML_LINE_WIDTH

        poly_style = ET.SubElement(style, 'PolyStyle')
        ET.SubElement(poly_style, 'color').text = KML_POLY_COLOR

    # --------------------------------------------------------------------------------
    def _generate_coordinates_body(self) -> str:
        """Generiert den inneren Textinhalt des <coordinates>-Tags unter Berücksichtigung
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        coord_strings: list[str] = []

        for p in self.data:
            if (
                    isinstance(p, GPSData)
                    and (not self.is_locked or p.fix > 0)
            ):
                # Formatierung: Longitude, Latitude, Altitude
                coord_strings.append(
                    f"{KML_COORDS_PREFIX}{p.longitude:.15g},{p.latitude:.15g},{p.altitude:.2f}\n"
                )

        return "\n" + "".join(coord_strings) + KML_COORDS_PREFIX

    # --------------------------------------------------------------------------------
    @staticmethod
    def _prettify_xml(element: ET.Element) -> str:
        """
        Gibt einen gut formatierten XML-String mit korrekten Einrückungen zurück.

        :param element: Das zu formatierende ET.Element.
        :return: Ein formatiertes XML als String.
        """
        rough_string: bytes = ET.tostring(element, encoding='utf-8')
        reparsed = minidom.parseString(rough_string)

        # Gibt das formierte XML ohne die XML-Deklarationszeile als UTF-8 String zurück
        return reparsed.toprettyxml(indent="    ", encoding='utf-8').decode('utf-8')


# -----------------------------------------------------------
# JSON Generator Klasse
# -----------------------------------------------------------


# ================================================================================
# ================================================================================
class JSONGenerator(BaseGenerator[list[KLVItem]]):
    """Konvertiert eine Liste von KLV-Elementen (Telemetry-Daten) in einen"""
    
    # --------------------------------------------------------------------------------
    def __init__(
            self,
            data: list[KLVItem],
            is_locked: bool = False,
            verbose: bool = False
    ) -> None:
        """
        Initialisiert den JSON-Generator mit einer Liste von KLVItem-Objekten.

        :param data: Liste von KLVItem-Objekten, die exportiert werden sollen.
        :param is_locked: Flag zur Steuerung valider Datenpunkte (wird an Basisklasse übergeben).
        :param verbose: Aktiviert erweiterte Konsolenausgaben während der Verarbeitung.
        """
        super().__init__(data, is_locked, verbose)

    # --------------------------------------------------------------------------------
    def generate(self) -> str:
        """Konvertiert die KLV-Elemente der Instanz in einen formatierten JSON-String.
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        if self.verbose:
            print(f"[JSONGenerator] Konvertiere {len(self.data)} KLV-Elemente in JSON.")

        json_list: list[dict[str, Any]] = []

        for p in self.data:
            # Sichere Dekodierung der Byte-Felder über die geerbten statischen Methoden der Basisklasse
            four_cc_str: str = self._safe_decode(p.fourCC, default=DEFAULT_STR)
            type_str: str = self._safe_decode(p.type, default=DEFAULT_TYPE)

            # Prüfen auf Existenz von p.value
            raw_data_repr: str = ''
            raw_data_hex: str = ''

            if p.value:
                # Slicing der Rohdaten
                sliced_data = p.value[:p.size * p.repeat]

                # Explizites Type-Narrowing für den Linter und die Laufzeitsicherheit
                if isinstance(sliced_data, bytes):
                    raw_data_repr = repr(sliced_data)
                    raw_data_hex = BaseGenerator._safe_join(sliced_data, ',')
                else:
                    # Fallback, falls p.value unerwartet kein bytes-Objekt war
                    raw_data_repr = repr(sliced_data)

            # Strukturierung des KLV-Datensatzes für das JSON-Objekt
            klv_dict: dict[str, Any] = {
                JSON_KEY_FOUR_CC: four_cc_str,
                JSON_KEY_TYPE: type_str,
                JSON_KEY_SIZE: p.size,
                JSON_KEY_REPEAT: p.repeat,
                JSON_KEY_DATA: raw_data_repr,
                JSON_KEY_RAWB: raw_data_hex,
            }

            json_list.append(klv_dict)

        # Generierung des finalen JSON-Strings unter Erhalt von Umlauten/Sonderzeichen
        return json.dumps(
            json_list,
            indent=JSON_INDENT,
            ensure_ascii=False
        )


# -----------------------------------------------------------
# HEX Generator Klasse
# -----------------------------------------------------------


# ================================================================================
# ================================================================================
class HEXGenerator(BaseGenerator[list[KLVItem]]):
    """Konvertiert eine Liste von KLV-Elementen in eine hexadezimale"""
    
    # --------------------------------------------------------------------------------
    def __init__(
            self,
            data: list[KLVItem],
            is_locked: bool = False,
            verbose: bool = False
    ) -> None:
        """
        Initialisiert den HEX-Generator mit einer Liste von KLVItem-Objekten.

        :param data: Liste von KLVItem-Objekten, deren Inhalt hexadezimal exportiert werden soll.
        :param is_locked: Flag zur Steuerung valider Datenpunkte (wird an Basisklasse übergeben).
        :param verbose: Aktiviert erweiterte Konsolenausgaben während der Verarbeitung.
        """
        super().__init__(data, is_locked, verbose)

    # --------------------------------------------------------------------------------
    def generate(self) -> str:
        """Konvertiert die KLV-Elemente der Instanz in eine Hex-Struktur und
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        if self.verbose:
            print(f"[HEXGenerator] Konvertiere {len(self.data)} KLV-Elemente in das Hex-Format.")

        json_list: list[dict[str, Any]] = []

        for p in self.data:
            # Sichere Dekodierung der Metadaten-Byte-Felder über die Basisklasse
            four_cc_str: str = self._safe_decode(p.fourCC, default=DEFAULT_STR)
            type_str: str = self._safe_decode(p.type, default=DEFAULT_TYPE)
            raw_data_repr: str = ''
            raw_data_hex: str = ''

            if p.value:
                # Slicing der Rohdaten
                sliced_data = p.value[:p.size * p.repeat]

                # Explizites Type-Narrowing für den Linter und die Laufzeitsicherheit
                if isinstance(sliced_data, bytes):
                    raw_data_repr = repr(sliced_data)  # erzeugt z.B. "b'\x00\x00\x00\x00\x00\x00`\xa1'"
                    raw_data_hex = BaseGenerator._safe_join(sliced_data, ',')
                else:
                    # Fallback, falls p.value unerwartet kein bytes-Objekt war
                    raw_data_repr = repr(sliced_data)

            # Strukturierung des KLV-Datensatzes für das Ausgabe-Objekt
            klv_dict: dict[str, Any] = {
                JSON_KEY_FOUR_CC: four_cc_str,
                JSON_KEY_TYPE: type_str,
                JSON_KEY_SIZE: p.size,
                JSON_KEY_REPEAT: p.repeat,
                JSON_KEY_DATA: raw_data_repr,
                JSON_KEY_RAWB: raw_data_hex,
            }

            json_list.append(klv_dict)

        # Generierung des finalen JSON-Strings unter Erhalt von Umlauten/Sonderzeichen
        return json.dumps(
            json_list,
            indent=JSON_INDENT,
            ensure_ascii=False
        )


# -----------------------------------------------------------
# GPS CSV Generator Klasse
# -----------------------------------------------------------


# ================================================================================
# ================================================================================
class GPSCSVGenerator(BaseGenerator[list[GPSData]]):
    """Erzeugt einen CSV-String mit GPS-Telemetriedaten aus einer Liste"""

    # CSV-Header-Zeile als Konstante extrahiert
    HEADER: Final[str] = (
        "Datetime,Latitude,Longitude,Altitude,Speed2D,Speed3D,Distance,"
        "Fix,Days2K,Secs,DOP,Units,No"
    )

    # --------------------------------------------------------------------------------
    def __init__(
        self,
        data: list[GPSData],
        is_locked: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialisiert den GPS-CSV-Generator mit Daten und Steuerparametern.

        :param data: Liste von GPSData-Objekten, die exportiert werden sollen.
        :param is_locked: Flag, ob nur valide/fixierte Datenpunkte genutzt werden sollen (p.fix > 0).
        :param verbose: Aktiviert erweiterte Konsolenausgaben während der Generierung.
        """
        super().__init__(data, is_locked, verbose)

    # --------------------------------------------------------------------------------
    def generate(self) -> str:
        """Konvertiert die GPS-Datenpunkte der Instanz basierend auf den gesetzten
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        lines: list[str] = [self.HEADER]

        for l_point in self.data:
            if (
                isinstance(l_point, GPSData)
                and (not self.is_locked or l_point.fix > 0)
            ):
                # Behandlung für das Einheiten-Feld (falls Liste, mit Kommata verbinden)
                units_string: str = (
                    ','.join(l_point.units)
                    if isinstance(l_point.units, list) and not isinstance(l_point.units, str)
                    else Str.safe_str(l_point.units)
                )

                lines.append(
                    f"{l_point.datetime},{l_point.latitude},{l_point.longitude},"
                    f"{l_point.altitude},{l_point.speed2d},{l_point.speed3d},"
                    f"{l_point.distance},{l_point.fix},{l_point.days2k},"
                    f"{l_point.secs},{l_point.DOP},{units_string},{l_point.no}"
                )

        if self.verbose:
            print(f"[GPSCSVGenerator] {len(lines) - 1} von {len(self.data)} GPS-Zeilen erfolgreich generiert.")

        return CSV_NEWLINE.join(lines)


# -----------------------------------------------------------
# Gyro CSV Generator Klasse
# -----------------------------------------------------------


# ================================================================================
# ================================================================================
class GyroCSVGenerator(BaseGenerator[list[GYROData]]):
    """Erzeugt einen CSV-String mit Gyroskop-Telemetriedaten aus einer Liste"""

    # CSV-Header-Zeile als Konstante extrahiert
    HEADER: Final[str] = "Datetime,Microseconds,GyroX,GyroY,GyroZ"

    # --------------------------------------------------------------------------------
    def __init__(
        self,
        data: list[GYROData],
        is_locked: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialisiert den Gyro-CSV-Generator mit Daten und Steuerparametern.

        :param data: Liste von GYROData-Objekten, die exportiert werden sollen.
        :param is_locked: Flag zur Steuerung valider Datenpunkte (wird an Basisklasse übergeben).
        :param verbose: Aktiviert erweiterte Konsolenausgaben während der Generierung.
        """
        super().__init__(data, is_locked, verbose)

    # --------------------------------------------------------------------------------
    def generate(self) -> str:
        """Konvertiert die Gyroskop-Datenpunkte der Instanz in einen
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        lines: list[str] = [self.HEADER]

        for l_point in self.data:
            # Gyro-Daten haben typischerweise keine fix/no Filterbedingungen wie GPS,
            # verhalten sich aber strukturell identisch bei der Zeilen-Generierung.
            lines.append(
                f"{l_point.datetime},{l_point.timestamp},{l_point.x},{l_point.y},{l_point.z}"
            )

        if self.verbose:
            print(f"[GyroCSVGenerator] {len(lines) - 1} Gyroskop-Zeilen erfolgreich generiert.")

        return CSV_NEWLINE.join(lines)


# -----------------------------------------------------------
# ACCL CSV Generator Klasse
# -----------------------------------------------------------


# ================================================================================
# ================================================================================
class ACCLCSVGenerator(BaseGenerator[list[ACCLData]]):
    """Erzeugt einen CSV-String mit Beschleunigungssensor-Telemetriedaten aus einer Liste"""

    # CSV-Header-Zeile als Konstante extrahiert
    HEADER: Final[str] = "Datetime,Microseconds,AcclX,AcclY,AcclZ"

    # --------------------------------------------------------------------------------
    def __init__(
        self,
        data: list[ACCLData],
        is_locked: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialisiert den ACCL-CSV-Generator mit Daten und Steuerparametern.

        :param data: Liste von ACCLData-Objekten, die exportiert werden sollen.
        :param is_locked: Flag zur Steuerung valider Datenpunkte (wird an Basisklasse übergeben).
        :param verbose: Aktiviert erweiterte Konsolenausgaben während der Generierung.
        """
        super().__init__(data, is_locked, verbose)

    # --------------------------------------------------------------------------------
    def generate(self) -> str:
        """Konvertiert die Beschleunigungs-Datenpunkte der Instanz in einen
        
        :return: (str) Beschreibung des Rückgabewerts.
        """

        lines: list[str] = [self.HEADER]

        for l_point in self.data:
            # Beschleunigungs-Daten haben standardmäßig keine fix/no Filterbedingungen wie GPS,
            # verhalten sich aber strukturell identisch bei der Zeilen-Generierung.
            lines.append(
                f"{l_point.datetime},{l_point.timestamp},{l_point.x},{l_point.y},{l_point.z}"
            )

        if self.verbose:
            print(f"[ACCLCSVGenerator] {len(lines) - 1} Beschleunigungs-Zeilen erfolgreich generiert.")

        return CSV_NEWLINE.join(lines)
