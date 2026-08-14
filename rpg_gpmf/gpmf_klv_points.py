#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 13-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm           : gpmf_klv_points.py
#  Version            : 2.0
#  Beschreibung       : Keine Beschreibung verfügbar.
#  Zeilen             : 695
#  Abhängigkeiten     : abc, argparse, bisect, cProfile, collections, configparser, ctypes, dataclasses, datetime, enum
#                       fractions, functools, glob, hashlib, http, inspect, io, json, locale, logging, math, mmap, os
#                       pathlib, pickle, platform, pstats, re, shutil, struct, subprocess, sys, tempfile, textwrap
#                       threading, time, traceback, typing, xml, zipfile, zoneinfo
#  Externe Frameworks : gpxpy, lxml, numpy, overpy, pandas, pyexiv2, requests, scipy, tzlocal, yaml
#  Eigene Frameworks  : rpg_geo, rpg_gpmf, rpg_gpx, rpg_utils
#  Klassen            : AcclItems, FaceItems, GPSItems, GyroItems, StreamItems
# ------------------------------------------------------------------------------

from typing import TypeVar, Generic, Any
from datetime import datetime, timedelta

from rpg_utils.utils_datetime import DateTimeUtils, TZ_UTC
from rpg_utils.utils_string import sstr
from rpg_gpmf.gpmf_klv_schema import ConsolidatedDEVCBlock, STRMBlock, KLVItem, GPSData, ACCLData, GYROData, FACEData
from rpg_gpmf.gpmf_klv_schema import DEFAULT_HEROVERSION
from rpg_gpmf.gpmf_klv_schema import FOURCC_STMP, FOURCC_GPS5, FOURCC_GPSU, FOURCC_GPSF, FOURCC_GPSP, FOURCC_GPS9, FOURCC_ACCL, FOURCC_GYRO, FOURCC_FACE
from rpg_gpx.gpx_schema import GeoPointTime
from rpg_gpmf.gpmf_klv import KLVParser
from rpg_gpx.gpx_utils import haversine


# Definiere den Typparameter
T = TypeVar('T')
# Konstanten für die GPMF GPS9 Index-Positionen zur Erhöhung der Wartbarkeit
GPS9_INDEX_DAYS: int = 5
GPS9_INDEX_SECONDS: int = 6
GPS9_MIN_ELEMENTS: int = 7  # Benötigt mindestens bis Index 6, also 7 Elemente

DEFAULT_LAT_LON: float = 0.0
DEFAULT_DOP: float = 0.0
DEFAULT_FIX: int = 0
DEFAULT_TIMESTAMP: int = 0


# ================================================================================
# Basis Klasse für alle Streams
#       main code that reads a stream of Items
# ================================================================================
class StreamItems(Generic[T]):
    # Nutze den Typparameter T für die Instanzvariable
    """Nutze den Typparameter T für die Instanzvariable"""

    parsed_items: list[T]

    # --------------------------------------------------------------------------------
    def __init__(self, data: dict[tuple, ConsolidatedDEVCBlock], fourccs: list[str], verbose: bool = False):
        """Initialisiert den Stream-Parser mit den konsolidierten DEVC-Blöcken.

        :param data: (dict[tuple[Any, ...], ConsolidatedDEVCBlock]) Mapping von Geräte-Keys auf Blöcke.
        :param fourccs: (list[str]) Liste der zu filternden FourCC-Codes.
        :param verbose: (bool) Aktiviert erweiterte Konsolenausgaben.
        """
        self.data = data
        self.fourccs = fourccs
        self.verbose = verbose
        self.parser = KLVParser()
        self.parsed_items = []
        self._parse_streams(self.fourccs)

    # ---------------------------------------------------------------------------------------
    def _parse_streams(self, fourccs: list[str]):
        """
        Verarbeitet Streams basierend auf den angegebenen FourCC-Codes.

        :param fourccs: (list[str]) Eine Liste von FourCC-Codes (z.B. ['ACCL', 'GYRO']).
        """
        for key, consolidated_devc in self.data.items():
            if len(key) < 2:
                continue
            device_id: int | str = key[0]
            device_name: str = str(key[1])
            device_version = consolidated_devc.devc_version
            streams = consolidated_devc.streams

            # Holen Sie die Basiszeit für den gesamten Geräteblock
            device_dt = self._get_base_datetime_from_streams(streams)

            # Iteriere über die Streams in diesem Block
            for stream_type, strm_block in streams.items():
                # Zugriff auf STRMBlock-Attribute über Punkt-Notation
                data_name = strm_block.strm_name if strm_block.strm_name else stream_type
                data_scal = strm_block.strm_scal
                data_type = strm_block.strm_type if strm_block.strm_type else ""
                data_unit = strm_block.strm_unit if strm_block.strm_unit else []
                chunks = strm_block.chunks if strm_block.chunks is not None else []

                # Prüfen, ob der Stream-Typ in der gewünschten Liste ist
                if stream_type in fourccs:
                    # Hier iterierst du über jedes einzelne KLVItem im Chunk
                    for chunk in chunks:
                        # Die Metadaten für diesen Stream sind bereits im strm_block-Objekt vorhanden.
                        stmp = self._get_parsed_value_from_raw(FOURCC_STMP, chunk)
                        # Wir übergeben jetzt nur das einzelne Daten-KLVItem an die Parsen-Methode.
                        parsed_data = self._parse_stream(
                            stream=chunk,                   # Die Liste von KLVItem, das die eigentlichen Daten enthält
                            device_id=device_id,
                            device_version=device_version,
                            device_name=device_name,
                            device_dt=device_dt,
                            stream_name=data_name,
                            stream_scal=data_scal,
                            stream_type=data_type,
                            stream_units=data_unit,
                            stream_timestamp=stmp,
                            verbose=self.verbose,
                        )

                        for point in parsed_data:
                            self.parsed_items.append(point)

    # ---------------------------------------------------------------------------------------
    @staticmethod
    def _safe_device_params(device_id: int | str | None = None, device_name: str | None = None, stream_name: str | None = None) -> tuple[int, str, str]:
        """Kurzbeschreibung für _safe_device_params.
        
        :param device_id: (int | str | None) Beschreibung von device_id.
        :param device_name: (str | None) Beschreibung von device_name.
        :param stream_name: (str | None) Beschreibung von stream_name.
        :return: (tuple[int, str, str]) Beschreibung des Rückgabewerts.
        """

        safe_device_id: int = int(device_id) if device_id is not None else 0
        safe_device_name = device_name if device_name is not None else ""
        safe_stream_name = stream_name if stream_name is not None else ""

        return safe_device_id, safe_device_name, safe_stream_name

    # ---------------------------------------------------------------------------------------
    def _parse_stream(self, stream: list[KLVItem],
                      device_id: int | str | None = None,
                      device_version: int = DEFAULT_HEROVERSION,
                      device_name: str | None = None,
                      device_dt: datetime | None = None,
                      stream_name: str | None = None,
                      stream_scal: KLVItem | None = None,
                      stream_type: str | list[str] = "",
                      stream_units: str | list[str] = "",
                      stream_timestamp: int = 0,
                      verbose: bool = False) -> list[T]:
        """Parsen eines einzelnen Stream-Chunks. Muss überschrieben werden.

        :param stream: (list[KLVItem]) Die Liste von KLVItem für den Chunk.
        :param device_id: (int | str | None) Die ID des Geräts.
        :param device_version: (int) Die Version des Geräts.
        :param device_name: (str | None) Der Name des Geräts.
        :param device_dt: (datetime | None) Der Basis-Zeitstempel für den Block.
        :param stream_name: (str | None) Der Name des Streams.
        :param stream_scal: (KLVItem | None) Skalierung der Werte des Streams.
        :param stream_type: (str | list[str]) Datentypen der Werte des Streams.
        :param stream_units: (str | list[str]) Die Einheiten des Streams.
        :param stream_timestamp: (int) Interner Timestamp des Streams.
        :param verbose: (bool) Aktiviert die Verbose-Ausgabe.
        :return: (list[T]) Liste der geparsten Datenobjekte.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    # ---------------------------------------------------------------------------------------
    def _get_parsed_value_from_streams(self, fourcc: str, strm_block: STRMBlock) -> list[Any]:
        """Sucht ein KLV-Item im gegebenen STRMBlock anhand seines FourCC und gibt dessen geparsten Werte zurück.

        :param fourcc: (str) Der gesuchte FourCC-Code.
        :param strm_block: (STRMBlock) Das STRMBlock-Objekt, das durchsucht werden soll.
        :return: (list[Any]) Liste der geparsten Werte aus allen Chunks.
        """
        # Schritt 1: Parsen der Metadaten aus dem STRMBlock
        scal = strm_block.strm_scal
        stype = strm_block.strm_type if strm_block.strm_type else ""

        # Schritt 2: über alle chunks des STRMBlock
        valuelist: list[Any] = []
        chunks = strm_block.chunks if strm_block.chunks is not None else []
        for chunk in chunks:
            # Schritt 3: Das KLVItem im Chunk finden
            klvitem = self._get_klv_item_by_fourcc(fourcc, chunk)
            # Schritt 4: Den Wert parsen und zurückgeben
            if klvitem is None:
                continue
            values = self.parser.parse_value(klvdata=klvitem, scal_item=scal, stype=stype)
            valuelist.append(values)

        return valuelist

    # ---------------------------------------------------------------------------------------
    def _get_parsed_value_from_stream(self, fourcc: str, chunk: list[KLVItem], scal_item: KLVItem | None = None, stype: str | list[str] = "") -> Any:
        """Sucht ein KLV-Item anhand seines FourCC und gibt dessen geparsten Wert zurück.

        :param fourcc: (str) Der gesuchte FourCC-Code.
        :param chunk: (list[KLVItem]) Eine Liste von KLVItem-Objekten, die durchsucht werden soll.
        :param scal_item: (KLVItem | None) Optionaler Skalierungsfaktor.
        :param stype: (str | list[str]) Optionaler Typ für komplexe Strukturen.
        :return: (Any) Der geparste Wert des gefundenen Items oder None.
        """
        klv_item = self._get_klv_item_by_fourcc(fourcc, chunk)
        if klv_item is None:
            return None

        return self.parse_value(klvdata=klv_item, scal_item=scal_item, stype=stype)

    # ---------------------------------------------------------------------------------------
    def _get_parsed_value_from_raw(self, fourcc: str, chunk: list[KLVItem]) -> Any:
        """
        Sucht ein KLV-Item anhand seines FourCC und gibt dessen geparsten Wert zurück.

        :param fourcc: (str) Der gesuchte FourCC-Code.
        :param chunk: (list[KLVItem]) Eine Liste von KLVItem-Objekten.
        :return: (Any) Der geparste Wert des gefundenen Items oder None.
        """
        return self._get_parsed_value_from_stream(fourcc, chunk)

    # ---------------------------------------------------------------------------------------
    @staticmethod
    def _get_klv_item_by_fourcc(fourcc: str, chunk: list[KLVItem]) -> KLVItem | None:
        """
        Sucht ein KLVItem in einer Liste von Chunks anhand seines FourCC-Codes.

        :param fourcc: (str) Der gesuchte FourCC-Code als String.
        :param chunk: (list[KLVItem]) Eine Liste von KLVItem-Objekten.
        :return: (KLVItem | None) Das gefundene KLVItem oder None.
        """
        return next((item for item in chunk if item.fourCC == fourcc), None)

    # ---------------------------------------------------------------------------------------
    def _get_base_datetime_from_streams(self, streams: dict[str, STRMBlock]) -> datetime | None:
        """
        Bestimmt die GPS-Basiszeit aus GPSU / GPS9-Streams.

        :param streams: (dict[str, STRMBlock]) Ein Dictionary, das STRMBlock-Objekte für jeden Stream-Typ enthält.
        :return: (datetime | None) Ein datetime-Objekt der Basiszeit oder None, falls keine gefunden wird.
        """
        stream_key = FOURCC_GPS5 if FOURCC_GPS5 in streams else FOURCC_GPS9

        gpsstreams = streams.get(stream_key)  # <-- Gibt None zurück, wenn stream_key nicht existiert
        # Der Stream existiert nicht, also keine GPS Daten
        if gpsstreams is None:
            return None

        # scal, stype aus dem Block lesen
        scal = gpsstreams.strm_scal
        stype = gpsstreams.strm_type if gpsstreams.strm_type else ""
        chunks = gpsstreams.chunks if gpsstreams.chunks is not None else []

        # Priorität 1: GPSU suchen
        if stream_key == FOURCC_GPS5:
            for stream in chunks:
                # Wir gehen davon aus, dass GPSU nur einen Wert hat
                gpsu_value = self._get_parsed_value_from_stream(FOURCC_GPSU, stream)
                if isinstance(gpsu_value, str):
                    try:
                        return DateTimeUtils.delta_time(gpsu_value)
                        # return DateTimeUtils.datetimestr_to_datetime(gpsu_value)
                    except ValueError:
                        # Falls das Format nicht passt, versuchen wir den nächsten Weg
                        pass

        # Priorität 2: GPS9 suchen
        if stream_key == FOURCC_GPS9:
            for stream in chunks:
                # Der Wert des GPS9-Items ist ein Tupel mit den GPS-Werten
                gps9_values = self._get_parsed_value_from_stream(stream_key, stream, scal, stype)

                # Die GPS9 Daten sind ein Tupel von (Fix, UTC-Datum, etc.)
                # Der GPMF-Standard gibt die Daten als (Days, Seconds, etc.)
                # Der korrekte Weg ist die GPSData-Klasse zu verwenden,
                # die wir in gpmf_schema definiert haben.
                # Hier greifen wir manuell auf die relevanten Werte zu.
                if isinstance(gps9_values, list) and len(gps9_values) > 0:
                    for gps9_value in gps9_values:
                        if isinstance(gps9_value, (list, tuple)) and len(gps9_value) >= GPS9_MIN_ELEMENTS:
                            days_2k = gps9_value[GPS9_INDEX_DAYS]
                            seconds = gps9_value[GPS9_INDEX_SECONDS]

                            # Basisdatum ist der 1. Januar 2000
                            start_date = DateTimeUtils.create_aware_base_datetime(year=2000, month=1, day=1)
                            # Berechne das Delta und die endgültige Zeit
                            delta = timedelta(days=days_2k, seconds=int(seconds), microseconds=int((seconds - int(seconds)) * 1000000))

                            # Berechnung der endgültigen Zeit in einem einzigen Schritt:
                            return DateTimeUtils.delta_time(start_date, delta)

        return None

    # ---------------------------------------------------------------------------------------
    def parse_value(self, klvdata: KLVItem | None, scal_item: KLVItem | None = None, stype: str | list[str] = "") -> Any:
        """Hilfsmethode zur Weiterleitung des Parsing-Vorgangs an den KLVParser.

        :param klvdata: (KLVItem | None) Das zu parsende KLVItem.
        :param scal_item: (KLVItem | None) Optionales Skalierungs-Item.
        :param stype: (str | list[str]) Der erwartete Datentyp.
        :return: (Any) Geparster Wert.
        """
        if klvdata is None:
            return None
        return self.parser.parse_value(klvdata, scal_item, stype)


# ================================================================================
# Main function: generate the list of points from klv items from binary (extracted) stream
#       main code that reads the points-Items
#       Annahme: Die Klasse StreamItems ist bereits definiert und verfügbar
# ================================================================================
class GPSItems(StreamItems[GPSData]):
    # ---------------------------------------------------------------------------------------
    """---------------------------------------------------------------------------------------"""

    def __init__(self, data: dict[tuple, ConsolidatedDEVCBlock]):
        """"Ruft den Konstruktor der Basisklasse auf und übergibt die Daten

        :param data: (dict[tuple[Any, ...], ConsolidatedDEVCBlock]) Die Rohdatenstruktur der Blöcke.
        """
        super().__init__(data, [FOURCC_GPS5, FOURCC_GPS9])

        self.gps_point: GeoPointTime | None = None
        self.gps_point_lock: GeoPointTime | None = None
        self.gps_dt: datetime | None = None
        self.gps_dt_lock: datetime | None = None

        if len(self.parsed_items) > 0:
            # GPS Points are in UTC, read first with and without lock
            result = self._read_first_gps_point(locked=False)
            if result:
                self.gps_dt, self.gps_point = result
            result = self._read_first_gps_point(locked=True)
            if result:
                self.gps_dt_lock, self.gps_point_lock = result

    # ---------------------------------------------------------------------------------------
    def _parse_stream(self, stream: list[KLVItem],
                      device_id: int | str | None = None,
                      device_version: int = DEFAULT_HEROVERSION,
                      device_name: str | None = None,
                      device_dt: datetime | None = None,
                      stream_name: str | None = None,
                      stream_scal: KLVItem | None = None,
                      stream_type: str | list[str] = "",
                      stream_units: str | list[str] = "",
                      stream_timestamp: int = 0,
                      verbose: bool = False) -> list[GPSData]:
        """Interne Hilfsmethode zum Parsen der GPS5/GPS9-Datenstrukturen.

        :param stream: (list[KLVItem]) Liste von KLVItems.
        :param device_id: (int | str | None) Geräte-ID.
        :param device_version: (int) Version des GoPro Modells.
        :param device_name: (str | None) Name des Geräts.
        :param device_dt: (datetime | None) Basiszeit.
        :param stream_name: (str | None) Name des Datenkanals.
        :param stream_scal: (KLVItem | None) Skalierungsfaktor.
        :param stream_type: (str | list[str]) Typen-Spezifikation.
        :param stream_units: (str | list[str]) Zugehörige Maßeinheiten.
        :param stream_timestamp: (int) Startzeitstempel.
        :param verbose: (bool) Debugausgabe umschalten.
        :return: (list[GPSData]) Liste generierter GPSData-Objekte.
        """
        if not stream or stream == []:
            if verbose:
                print(f"Warning: No data found in stream '{sstr(stream_name)}'.")
            return []

        stream_key = FOURCC_GPS5 if FOURCC_GPS5 in stream else FOURCC_GPS9  # -> wegen KLVItem.__eq__ funktioniert es
        if not stream_key:
            if verbose:
                print(f"Warning: No {FOURCC_GPS5} or {FOURCC_GPS9} data found in this chunk.")
            return []

        # Vereinfache den Aufruf von parse_value basierend auf dem Stream-Typ
        pointlist = self._get_parsed_value_from_stream(stream_key, stream, stream_scal, stream_type)
        if not pointlist:
            if verbose:
                print("Warning: Parsed GPS point list is empty.")
            return []

        # device params setzen
        device_id, device_name, stream_name = self._safe_device_params(device_id, device_name, stream_name)

        dt_increment = timedelta(seconds=1.0 / len(pointlist))
        base_date = DateTimeUtils.create_aware_base_datetime(year=2000, month=1, day=1)
        data: list[GPSData] = []
        p1_lat: float | None = None
        p1_lon: float | None = None

        effective_device_dt = device_dt if device_dt is not None else base_date

        for i, klvdata in enumerate(pointlist):
            if not isinstance(klvdata, (list, tuple)) or len(klvdata) < 5:
                continue

            lat = float(klvdata[0]) if klvdata[0] is not None else DEFAULT_LAT_LON
            lon = float(klvdata[1]) if klvdata[1] is not None else DEFAULT_LAT_LON
            alt = float(klvdata[2]) if klvdata[2] is not None else 0.0
            sp2d = float(klvdata[3]) if klvdata[3] is not None else 0.0
            sp3d = float(klvdata[4]) if klvdata[4] is not None else 0.0
            distance = haversine(p1_lat, p1_lon, lat, lon)

            if stream_key == FOURCC_GPS5:
                gpsp_val = self._get_parsed_value_from_raw(FOURCC_GPSP, stream)
                gpsf_val = self._get_parsed_value_from_raw(FOURCC_GPSF, stream)
                dt_utc = effective_device_dt + i * dt_increment
                days2k = (dt_utc - effective_device_dt).days
                secs = int((dt_utc - effective_device_dt).seconds + (dt_utc - effective_device_dt).microseconds / 1_000_000)
                dop = float(gpsp_val) / 100.0 if gpsp_val else 0.0
                fix = gpsf_val if gpsf_val else 0
            else:
                days2k = int(klvdata[5]) if len(klvdata) > 5 and klvdata[5] is not None else 0
                secs = int(klvdata[6]) if len(klvdata) > 6 and klvdata[6] is not None else 0
                dop = float(klvdata[7]) if len(klvdata) > 7 and klvdata[7] is not None else DEFAULT_DOP
                fix = int(klvdata[8]) if len(klvdata) > 8 and klvdata[8] is not None else DEFAULT_FIX
                dt_utc = DateTimeUtils.delta_time(base_date, timedelta(days=days2k, seconds=int(secs), milliseconds=round((secs - int(secs)) * 1000)))
                dt_utc = dt_utc if dt_utc is not None else base_date

            s = GPSData(
                device_id=device_id,
                device_name=device_name,
                description=stream_name,
                timestamp=stream_timestamp,
                datetime=dt_utc,
                latitude=lat,
                longitude=lon,
                altitude=alt,
                speed2d=sp2d,
                speed3d=sp3d,
                units=stream_units,
                distance=distance,
                days2k=days2k,
                secs=secs,
                DOP=dop,
                fix=fix,
                no=i,
            )
            data.append(s)
            p1_lat, p1_lon = lat, lon

        return data

    # -----------------------------------------------------------
    # Read first Point of GPX data
    # -----------------------------------------------------------
    def _read_first_gps_point(self, locked=False) -> tuple[datetime, GeoPointTime] | None:
        """Gibt den allerersten validierten GPS-Punkt zurück.

        :param locked: (bool) Schalter, um nur fixierte Datenpunkte (>0) zu berücksichtigen.
        :return: (tuple[datetime, GeoTimedPoint] | None) Erstes valides Koordinatenpaar.
        """
        for l_point in self.parsed_items:
            if locked and (l_point.fix <= 0):
                continue
            return l_point.datetime, GeoPointTime(latitude=l_point.latitude, longitude=l_point.longitude, elevation=l_point.altitude, timestamp=l_point.datetime, tz=TZ_UTC)
        return None


# ================================================================================
# Main function: generate the list of points from klv items from binary (extracted) stream
#       main code that reads the points-Items
# ================================================================================
class GyroItems(StreamItems[GYROData]):
    """Spezialisierte Klasse zur Verarbeitung von Gyroskop-Sensordaten."""

    # --------------------------------------------------------------------------------
    def __init__(self, data: dict[tuple, ConsolidatedDEVCBlock], verbose: bool = False):
        """Initialisiert den Gyroskopspeicher.

        :param data: (dict[tuple[Any, ...], ConsolidatedDEVCBlock]) Die Rohdatenstruktur der Blöcke.
        :param verbose: (bool) Debugausgabe umschalten.
        """
        super().__init__(data, [FOURCC_GYRO], verbose)

    # ---------------------------------------------------------------------------------------
    def _parse_stream(self, stream: list[KLVItem],
                      device_id: int | str | None = None,
                      device_version: int = DEFAULT_HEROVERSION,
                      device_name: str | None = None,
                      device_dt: datetime | None = None,
                      stream_name: str | None = None,
                      stream_scal: KLVItem | None = None,
                      stream_type: str | list[str] = "",
                      stream_units: str | list[str] = "",
                      stream_timestamp: int = 0,
                      verbose: bool = False) -> list[GYROData]:
        """Parses GYRO KLV items into GYROData objects.
        
        :param stream: (list[KLVItem]) Beschreibung von stream.
        :param device_id: (int | str | None) Beschreibung von device_id.
        :param device_version: (int) Beschreibung von device_version.
        :param device_name: (str | None) Beschreibung von device_name.
        :param device_dt: (datetime | None) Beschreibung von device_dt.
        :param stream_name: (str | None) Beschreibung von stream_name.
        :param stream_scal: (KLVItem | None) Beschreibung von stream_scal.
        :param stream_type: (str | list[str]) Beschreibung von stream_type.
        :param stream_units: (str | list[str]) Beschreibung von stream_units.
        :param stream_timestamp: (int) Beschreibung von stream_timestamp.
        :param verbose: (bool) Beschreibung von verbose.
        :return: (list[GYROData]) Beschreibung des Rückgabewerts.
        """

        # Vereinfache den Aufruf von parse_value basierend auf dem Stream-Typ
        stream_key = FOURCC_GYRO
        pointlist = self._get_parsed_value_from_stream(stream_key, stream, stream_scal, stream_type)
        if not pointlist:
            if verbose:
                print(f"Warning: No {stream_key} data found in this stream.")
            return []

        # device params setzen
        device_id, device_name, stream_name = self._safe_device_params(device_id, device_name, stream_name)

        # Berechnen Sie das Start-Datum einmalig
        effective_device_dt = device_dt if device_dt is not None else DateTimeUtils.create_aware_base_datetime(year=2000, month=1, day=1)
        start_datetime = effective_device_dt + timedelta(microseconds=stream_timestamp)
        # Berechnen Sie das Zeitinkrement einmalig
        dt_increment = timedelta(seconds=1.0 / len(pointlist))

        data: list[GYROData] = []
        for i, klvdata in enumerate(pointlist):
            # Erstelle das Objekt mit den Geräte- und Versionsinformationen
            val_z = float(klvdata[2]) if klvdata[2] is not None else 0.0
            val_x = float(klvdata[1]) if klvdata[1] is not None else 0.0
            val_y = float(klvdata[0]) if klvdata[0] is not None else 0.0

            s = GYROData(
                device_id=device_id,
                device_name=device_name,
                description=stream_name,
                timestamp=stream_timestamp + i * int(dt_increment.total_seconds() * 1_000_000),
                datetime=start_datetime + i * dt_increment,
                z=val_z,
                x=-1.0 * val_x,
                y=val_y,
                no=i,
            )
            # Die Koordinaten-Anpassung sollte im GYROData-Objekt behandelt werden.
            # Alternativ können Sie es wie hier belassen.
            if device_version == 1:
                s = s.with_coords(z=val_z, x=val_x, y=-1.0 * val_y)
            elif device_version == 0:
                s = s.with_coords(z=val_y, x=val_x, y=val_z)

            data.append(s)

        return data


# ================================================================================
# Main function: generate the list of points from klv items from binary (extracted) stream
#       main code that reads the points-Items
# ================================================================================
class AcclItems(StreamItems[ACCLData]):
    """Spezialisierte Klasse zur Verarbeitung von Beschleunigungssensordaten."""

    # --------------------------------------------------------------------------------
    def __init__(self, data: dict[tuple[Any, ...], ConsolidatedDEVCBlock], verbose: bool = False):
        """Initialisiert den Beschleunigungsspeicher.

        :param data: (dict[tuple[Any, ...], ConsolidatedDEVCBlock]) Die Rohdatenstruktur der Blöcke.
        :param verbose: (bool) Debugausgabe umschalten.
        """
        super().__init__(data, [FOURCC_ACCL], verbose)

    # ---------------------------------------------------------------------------------------
    def _parse_stream(self, stream: list[KLVItem],
                      device_id: int | str | None = None,
                      device_version: int = DEFAULT_HEROVERSION,
                      device_name: str | None = None,
                      device_dt: datetime | None = None,
                      stream_name: str | None = None,
                      stream_scal: KLVItem | None = None,
                      stream_type: str | list[str] = "",
                      stream_units: str | list[str] = "",
                      stream_timestamp: int = 0,
                      verbose: bool = False) -> list[ACCLData]:
        """Parst die Beschleunigungsvektoren des Sensors.

        :param stream: (list[KLVItem]) Liste von KLVItems.
        :param device_id: (int | str | None) Geräte-ID.
        :param device_version: (int) Version des GoPro Modells.
        :param device_name: (str | None) Name des Geräts.
        :param device_dt: (datetime | None) Basiszeit.
        :param stream_name: (str | None) Name des Datenkanals.
        :param stream_scal: (KLVItem | None) Skalierungsfaktor.
        :param stream_type: (str | list[str]) Typen-Spezifikation.
        :param stream_units: (str | list[str]) Zugehörige Maßeinheiten.
        :param stream_timestamp: (int) Startzeitstempel.
        :param verbose: (bool) Debugausgabe umschalten.
        :return: (list[ACCLData]) Liste verarbeiteter Beschleunigungswerte.
        """
        stream_key = FOURCC_ACCL
        # Vereinfache den Aufruf von parse_value basierend auf dem Stream-Typ
        pointlist = self._get_parsed_value_from_stream(stream_key, stream, stream_scal, stream_type)
        if not pointlist:
            if verbose:
                print(f"Warning: No {stream_key} data found in this stream.")
            return []

        # device params setzen
        device_id, device_name, stream_name = self._safe_device_params(device_id, device_name, stream_name)

        # Berechnen Sie das Start-Datum einmalig
        effective_device_dt = device_dt if device_dt is not None else DateTimeUtils.create_aware_base_datetime(year=2000, month=1, day=1)
        start_datetime = effective_device_dt + timedelta(microseconds=stream_timestamp)
        dt_increment = timedelta(seconds=1.0 / len(pointlist))

        data: list[ACCLData] = []
        for i, klvdata in enumerate(pointlist):
            # Erstelle das Objekt mit den Geräte- und Versionsinformationen

            val_z = float(klvdata[2]) if klvdata[2] is not None else 0.0
            val_x = float(klvdata[1]) if klvdata[1] is not None else 0.0
            val_y = float(klvdata[0]) if klvdata[0] is not None else 0.0

            s = ACCLData(
                device_id=device_id,
                device_name=device_name,
                description=stream_name,
                timestamp=stream_timestamp + i * int(dt_increment.total_seconds() * 1_000_000),
                datetime=start_datetime + i * dt_increment,
                z=val_z,
                x=-1 * val_x,
                y=val_y,
                no=i,
            )

            # Die Koordinaten-Anpassung sollte im ACCLData-Objekt behandelt werden.
            # Alternativ können Sie es wie hier belassen.
            if device_version == 1:
                s = s.with_coords(z=val_z, x=val_x, y=-1.0 * val_y)
            elif device_version == 0:
                s = s.with_coords(z=val_y, x=val_x, y=val_z)

            data.append(s)

        return data


# ================================================================================
# Main function: generate the list of points from klv items from binary (extracted) stream
#       main code that reads the points-Items
# ================================================================================
class FaceItems(StreamItems[FACEData]):
    """Spezialisierte Klasse zur Verarbeitung von Gesichtserkennungs-Metadaten (FACE)."""

    # --------------------------------------------------------------------------------
    def __init__(self, data: dict[tuple[Any, ...], ConsolidatedDEVCBlock], verbose: bool = False):
        """Initialisiert den Gesichtserkennungsspeicher.

        :param data: (dict[tuple[Any, ...], ConsolidatedDEVCBlock]) Die Rohdatenstruktur der Blöcke.
        :param verbose: (bool) Debugausgabe umschalten.
        """
        super().__init__(data, [FOURCC_FACE], verbose)

    # --------------------------------------------------------------------------------
    def _parse_stream(self, stream: list[KLVItem],
                      device_id: int | str | None = None,
                      device_version: int = DEFAULT_HEROVERSION,
                      device_name: str | None = None,
                      device_dt: datetime | None = None,
                      stream_name: str | None = None,
                      stream_scal: KLVItem | None = None,
                      stream_type: str | list[str] = "",
                      stream_units: str | list[str] = "",
                      stream_timestamp: int = 0,
                      verbose: bool = False) -> list[FACEData]:
        """Parst die erfassten Gesichtsbegrenzungsboxen und IDs.

        :param stream: (list[KLVItem]) Liste von KLVItems.
        :param device_id: (int | str | None) Geräte-ID.
        :param device_version: (int) Version des GoPro Modells.
        :param device_name: (str | None) Name des Geräts.
        :param device_dt: (datetime | None) Basiszeit.
        :param stream_name: (str | None) Name des Datenkanals.
        :param stream_scal: (KLVItem | None) Skalierungsfaktor.
        :param stream_type: (str | list[str]) Typen-Spezifikation.
        :param stream_units: (str | list[str]) Zugehörige Maßeinheiten.
        :param stream_timestamp: (int) Startzeitstempel.
        :param verbose: (bool) Debugausgabe umschalten.
        :return: (list[FACEData]) Liste mit erfassten Gesichtsdaten.
        """
        stream_key = FOURCC_FACE
        pointlist = self._get_parsed_value_from_stream(stream_key, stream, stream_scal, stream_type)
        if not pointlist:
            if verbose:
                print(f"Warning: No {stream_key} data found in this stream.")
            return []

        # device params setzen
        device_id, device_name, stream_name = self._safe_device_params(device_id, device_name, stream_name)

        effective_device_dt = device_dt if device_dt is not None else DateTimeUtils.create_aware_base_datetime(year=2000, month=1, day=1)
        start_datetime = effective_device_dt + timedelta(microseconds=stream_timestamp)
        dt_increment = timedelta(seconds=1.0 / len(pointlist))

        data: list[FACEData] = []
        for i, klvdata in enumerate(pointlist):
            s = FACEData(
                device_id=device_id,
                device_name=device_name,
                description=stream_name,
                timestamp=stream_timestamp + i * int(dt_increment.total_seconds() * 1_000_000),
                datetime=start_datetime + i * dt_increment,
                project=klvdata,
                no=i,
            )

            s = s.with_coords(project='')
            data.append(s)

        return data
