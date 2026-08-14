#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 13-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm           : gpmf_klv.py
#  Version            : 2.0
#  Beschreibung       : Keine Beschreibung verfügbar.
#  Zeilen             : 839
#  Abhängigkeiten     : abc, argparse, bisect, cProfile, collections, configparser, ctypes, dataclasses, datetime, enum
#                       fractions, functools, glob, hashlib, http, inspect, io, json, locale, logging, math, mmap, os
#                       pathlib, pickle, platform, pstats, re, shutil, struct, subprocess, sys, tempfile, textwrap
#                       threading, time, traceback, typing, xml, zipfile, zoneinfo
#  Externe Frameworks : gpxpy, lxml, numpy, overpy, pandas, pyexiv2, requests, scipy, tzlocal, yaml
#  Eigene Frameworks  : rpg_geo, rpg_gpmf, rpg_gpx, rpg_utils
#  Klassen            : KLVItemList, KLVParser
# ------------------------------------------------------------------------------

import struct
from typing import Any, Iterator, Final, TypeAlias
from dataclasses import replace
from collections import defaultdict

from rpg_utils.utils_core import log_to_callback, CallbackTag as Tag
from rpg_utils.utils_filepath import ENCODING_UTF8
from rpg_utils.utils_math import MathUtils
from rpg_gpmf.gpmf_klv_schema import GPMF_TYPE_MAP, STRUCT_SIZES_MAP, FOURCC_METADATA_MAP, GOPRO_VERSION_MAP
from rpg_gpmf.gpmf_klv_schema import KEY_CLASS_NAME, KEY_DESCRIPTION, DEFAULT_HEROVERSION
from rpg_gpmf.gpmf_klv_schema import FOURCC_DEVC, FOURCC_DVID, FOURCC_DVNM, FOURCC_STRM, FOURCC_STNM, FOURCC_SCAL, FOURCC_TYPE, FOURCC_UNIT, FOURCC_SIUN
from rpg_gpmf.gpmf_klv_schema import KLVItem
from rpg_gpmf.gpmf_klv_schema import ConsolidatedDEVCBlock, DEVCBlock, STRMBlock

# Type Alias für bessere Lesbarkeit
KlvDictKey: TypeAlias = tuple[int | str | None, str | None]

# Konstanten
BIG_ENDIAN_PREFIX: Final[str] = ">"
DEFAULT_DEVICE_NAME: Final[str] = "GoPro"
DEFAULT_DEVICE_ID: Final[int] = 0
CHAR_TYPE_CODE: Final[str] = "c"
STRING_TYPE_SUFFIX: Final[str] = "s"
LATIN1_ENCODING: Final[str] = "latin1"
PREFIX_LENGTH_DEVICE: Final[int] = 5
# format: fourCC (4s), type (c), size (B), repeat (H)
BINARY_FORMAT: Final[str] = ">4scBH"


# ---------------------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------------------
def map_type(par_mtype: bytes | str | int) -> str | None:
    """
    Transformiert ein GPMF-Typzeichen in einen Python-struct Formatcode.
    Sorgt dafür, dass verschiedene Eingabetypen (int, str, bytes) konsistent
    auf das interne Mapping angewendet werden.

    :param par_mtype: (bytes | str | int) Das Typzeichen des GPMF-Elements.
    :return: (str | None) Der entsprechende struct-Formatcode aus GPMF_TYPE_MAP oder None.
    """
    # Sicherstellen, dass der Schlüssel für das Mapping ein bytes-Objekt ist[cite: 1]
    if isinstance(par_mtype, int):
        # int-Eingabe (z.B. 99 für 'c') in bytes umwandeln[cite: 1]
        key = bytes([par_mtype])
    elif isinstance(par_mtype, str):
        # str-Eingabe (z.B. 'c') in latin1 (1-zu-1 Byte) kodieren[cite: 1]
        key = par_mtype.encode(LATIN1_ENCODING)
    else:
        # bytes-Eingabe (z.B. b'c') direkt verwenden[cite: 1]
        key = par_mtype

    # Die get()-Methode wird auf das MapType-Dictionary mit bytes-Schlüsseln angewendet[cite: 1]
    return GPMF_TYPE_MAP.get(key)


# ---------------------------------------------------------------------------------------
def map_size(stype: str) -> int:
    """
    Bestimmt die Byte-Länge eines struct-Typs.

    :param stype: (str) Der struct-Formatcode (z. B. 'I', '16s').
    :return: (int) Die Länge in Bytes.
    :raises ValueError: Wenn der Typ unbekannt ist oder nicht berechnet werden kann.
    """
    # 1. Prüfung gegen das vordefinierte Mapping
    if stype in STRUCT_SIZES_MAP:
        return STRUCT_SIZES_MAP[stype]

    # 2. Fallback auf die interne Python-Funktion
    try:
        # Die calcsize()-Funktion benötigt einen Byte-Order-Char.
        # Wir fügen '>' (Big-Endian) hinzu, da das der Standard in GPMF ist.
        return struct.calcsize(BIG_ENDIAN_PREFIX + stype)
    except (struct.error, TypeError):
        # Falls struct.calcsize den Typ nicht kennt, ist er ungültig
        raise ValueError(f"Unbekannter Typ {stype}")


# ---------------------------------------------------------------------------------------
# KLVItemList: alle KLVItems der GoPro Metadaten
# ---------------------------------------------------------------------------------------


# ================================================================================
# ================================================================================
class KLVItemList:
    """Parser für die binäre GPMF-Datenstruktur (GoPro Metadata Format)."""

    # Konstanten für das binäre Layout des GPMF-Headers
    HEADER_SIZE: Final[int] = struct.calcsize(BINARY_FORMAT)

    # --------------------------------------------------------------------------------
    def __init__(self, data: bytes, verbose: bool = False) -> None:
        """
        Initialisiert die KLV-Liste mit den binären Rohdaten.

        :param data: (bytes) Die binären GPMF-Rohdaten.
        :param verbose: (bool) Flag zur Aktivierung erweiterter Log-Ausgaben.
        """
        self.data: bytes = data
        self.verbose: bool = verbose

        # Speicher für die geparsten Datenstrukturen
        self.klvstruct: list[KLVItem] = []
        self.klvlist: list[KLVItem] = []

        # Dictionary für die konsolidierte Sicht der DEVC-Blöcke
        # Key: (Device-ID, Device-Name)
        self.klvdict: dict[tuple[int | str | None, str | None], ConsolidatedDEVCBlock] = {}

        # Hilfsklasse zum Parsen der Einzelwerte innerhalb der Items
        self.parser: KLVParser = KLVParser()

    # ---------------------------------------------------------------------------------------
    def create_itemstruct(self) -> list[KLVItem]:
        """Erstellt die hierarchische Struktur der KLV-Items aus den Rohdaten.
        
        :return: (list[KLVItem]) Beschreibung des Rückgabewerts.
        """

        if self.klvstruct:
            return self.klvstruct

        klvstruct: list[KLVItem] = []
        offset: int = 0
        data_len: int = len(self.data)

        while offset < data_len:
            try:
                # Prüfen, ob noch genügend Daten für einen Header vorhanden sind
                if offset + self.HEADER_SIZE > data_len:
                    break

                # Header entpacken: FourCC (4s), Type (c), Size (B), Repeat (H)
                fourCC_raw, typec, size, repeat = struct.unpack_from(BINARY_FORMAT, self.data, offset)

                # FourCC dekodieren (z.B. b'DEVC' -> "DEVC")
                fourCC: str = fourCC_raw.decode(ENCODING_UTF8, errors="replace")

                # Gesamtlänge der Nutzlast berechnen
                length: int = size * repeat
                # GPMF ist auf 32-Bit (4 Bytes) ausgerichtet. Padding-Länge berechnen.
                plength: int = MathUtils.ceil4(length)

                # Sicherheitsprüfung: Reichen die Daten für die deklarierte Nutzlast?
                if offset + self.HEADER_SIZE + length > data_len:
                    log_to_callback(Tag.WARN, f"Unerwartetes Ende der Daten bei FourCC {fourCC} an Offset {offset}.")
                    break

                # Daten-Payload extrahieren
                data_slice: bytes = self.data[offset + self.HEADER_SIZE: offset + self.HEADER_SIZE + length]

                # Rekursion für verschachtelte Blöcke (DEVC und STRM)
                # Nur wenn ein gültiger Typ-Mapper existiert (Container haben oft Typ 0 oder '\0')
                parsed_value: bytes | list[KLVItem]
                if fourCC in [FOURCC_DEVC, FOURCC_STRM]:
                    # Erstelle eine neue Instanz von KLVItemList für die Sub-Daten
                    parsed_value = KLVItemList(data_slice, self.verbose).create_itemstruct()
                else:
                    # Einfache Daten bleiben vorerst als Bytes erhalten
                    parsed_value = data_slice

                # Item zur Struktur hinzufügen
                klvstruct.append(KLVItem(
                    fourCC=fourCC,
                    type=typec,
                    size=size,
                    repeat=repeat,
                    value=parsed_value
                ))

                # Offset für das nächste Element weitersetzen (inkl. Header und Padding)
                offset += self.HEADER_SIZE + plength

            except (struct.error, Exception) as e:
                log_to_callback(Tag.ERR, f"Fehler beim Parsen der KLV-Struktur bei Offset {offset}: {e}")
                # Im Fehlerfall versuchen wir, ein Byte weiterzugehen, um den nächsten Header zu finden
                offset += 1

        self.klvstruct = klvstruct
        return self.klvstruct

    # ---------------------------------------------------------------------------------------
    def create_itemlist(self) -> list[KLVItem]:
        """Erstellt eine flache Liste aller KLV-Elemente aus der hierarchischen Struktur.
        
        :return: (list[KLVItem]) Beschreibung des Rückgabewerts.
        """

        # --------------------------------------------------------------------------------
        def get_all_items_recursive(items: list[KLVItem]) -> Iterator[KLVItem]:
            """
            Innerer Generator zur rekursiven Iteration durch die KLV-Struktur.

            :param items: (list[KLVItem]) Die Liste der KLV-Items.
            :yield: (KLVItem) Das nächste flache KLV-Item.
            """
            for item in items:
                # Falls das Item ein Container ist, erstellen wir eine Kopie mit leerem Value
                # für die flache Liste, um Daten-Duplikate zu vermeiden.
                if item.fourCC in [FOURCC_DEVC, FOURCC_STRM]:
                    # Wir nutzen dataclasses.replace für eine saubere Kopie des Immutable-Objekts
                    new_item = replace(item, value=b'')
                    yield new_item
                else:
                    yield item

                # Wenn das Item Sub-Elemente hat (rekursive Struktur), werden diese ebenfalls durchlaufen
                if isinstance(item.value, list):
                    yield from get_all_items_recursive(item.value)

        # Sicherstellen, dass die hierarchische Struktur existiert
        if not self.klvstruct:
            self.create_itemstruct()

        # Falls nach dem Parsen immer noch keine Daten da sind
        if not self.klvstruct:
            return []

        # Den Generator in eine Liste umwandeln und speichern
        self.klvlist = list(get_all_items_recursive(self.klvstruct))
        return self.klvlist

    # ---------------------------------------------------------------------------------------
    def create_itemdict(self) -> dict[tuple[int | str | None, str | None], ConsolidatedDEVCBlock]:
        """Konsolidiert die hierarchischen KLV-Daten in ein Dictionary, gruppiert nach Geräten (DEVC).
        
        :return: (dict[tuple[int | str | None, str | None], ConsolidatedDEVCBlock]) Beschreibung des Rückgabewerts.
        """

        if self.klvdict:
            return self.klvdict

        if not self.klvstruct:
            self.create_itemstruct()

        # Temporäres Dictionary für die Ergebnisse
        consolidated_results: dict[tuple[int, str], ConsolidatedDEVCBlock] = {}

        for item in self.klvstruct:
            # Wir verarbeiten nur DEVC-Container, die eine Liste von Unterelementen enthalten
            if item.fourCC == FOURCC_DEVC and isinstance(item.value, list):
                # Verarbeite den einzelnen DEVC-Block
                processed_data: DEVCBlock | None = self._process_single_devc_block(item.value)

                if not processed_data:
                    if self.verbose:
                        log_to_callback(Tag.STATUS, "Warnung: Überspringe leeren oder fehlerhaften Datenblock.")
                    continue

                # Wir bestimmen die Device-ID. Falls None, nutzen wir die Konstante DEFAULT_DEVICE_ID (0).
                raw_id = processed_data.devc_id
                c_id: int = raw_id if raw_id is not None else 0
                raw_name = processed_data.devc_name
                c_name: str = raw_name if raw_name is not None else "GoPro"
                # Jetzt ist sichergestellt, dass key vom Typ tuple[int | str, str] ist
                key: tuple[int, str] = (c_id, c_name)

                if self.verbose:
                    log_to_callback(Tag.STATUS, f"Verarbeite DEVC-Block für Gerät: {c_name} (ID: {c_id})")

                # Falls das Gerät noch nicht im Dictionary existiert, neu anlegen
                if key not in consolidated_results:
                    if self.verbose:
                        log_to_callback(Tag.STATUS, f"Neues Gerät im Stream gefunden: {c_name}")

                    consolidated_results[key] = ConsolidatedDEVCBlock(
                        devc_id=c_id,
                        devc_name=c_name,
                        devc_version=processed_data.devc_version
                    )

                target: ConsolidatedDEVCBlock = consolidated_results[key]

                # 1. Attribute des Geräts aktualisieren/mergen
                if processed_data.attributes:
                    target.attributes.update(processed_data.attributes)

                # 2. Streams (STRM) verarbeiten und Chunks anhängen
                if processed_data.streams:
                    for s_type, blocks in processed_data.streams.items():
                        if not blocks:
                            continue

                        # Wenn der Stream-Typ (z.B. 'ACCL') im Zielgerät noch fehlt, initialisieren
                        if s_type not in target.streams:
                            first_block = blocks[0]
                            target.streams[s_type] = STRMBlock(
                                strm_name=first_block.strm_name,
                                strm_scal=first_block.strm_scal,
                                strm_type=first_block.strm_type,
                                strm_unit=first_block.strm_unit,
                                chunks=[]
                            )

                        # Die Chunks (Datenpakete) aus allen Blöcken dieses Typs hinzufügen
                        strm_target: STRMBlock = target.streams[s_type]
                        # 1. Lokale Referenz holen
                        current_chunks = strm_target.chunks
                        # 2. Falls None, initialisieren wir sie lokal und weisen sie dem Target zu
                        if current_chunks is None:
                            current_chunks = []
                            strm_target.chunks = current_chunks

                        # Jetzt weiß der Typprüfer zu 100%, dass current_chunks eine Liste ist
                        for b in blocks:
                            if b.chunks:
                                current_chunks.extend(b.chunks)

        if self.verbose:
            prefix = 'Generiere KLV'
            if consolidated_results:
                log_to_callback(Tag.STATUS, prefix, "Analyse abgeschlossen! Konsolidierte Daten nach ID und Name:")
                for key, devc_data in consolidated_results.items():
                    devc_id, devc_name = key
                    log_to_callback(Tag.STATUS, prefix, f"Gerät mit ID: {devc_id} (Name: {devc_name}) ---")

                    if devc_data.attributes:
                        log_to_callback(Tag.STATUS, prefix, "- Attribute:")
                        for attr_type, item in devc_data.attributes.items():
                            log_to_callback(Tag.STATUS, prefix, f"-- '{attr_type}': {item}")

                        if devc_data.streams:
                            log_to_callback(Tag.STATUS, prefix, "- Streams:")
                            for strm_type, stream_block in devc_data.streams.items():
                                log_to_callback(Tag.STATUS, prefix, f"-- '{strm_type}': {len(stream_block.chunks or [])} Chunk(s) gefunden.")
                    else:
                        log_to_callback(Tag.STATUS, prefix, "-- Keine Streams in diesem Block gefunden.")
            else:
                log_to_callback(Tag.WARN, prefix, "Keine Streams gefunden. Überprüfen Sie die Eingabedaten.")

        self.klvdict = consolidated_results
        return self.klvdict

    # ---------------------------------------------------------------------------------------
    @staticmethod
    def _process_version_devc_block(devc_name: str) -> int:
        """
        Bestimmt die GoPro-Generation basierend auf dem Gerätenamen.
        Dies wird für die korrekte Interpretation spezifischer Datenfelder benötigt.

        :param devc_name: (str | None) Der extrahierte Name des Geräts (z.B. "GoPro Hero 10").
        :return: (int) Die erkannte Major-Version oder die Standardversion (DEFAULT_HEROVERSION).
        """
        if not devc_name:
            log_to_callback(Tag.STATUS, "Kein Gerätename zur Versionsbestimmung vorhanden. Nutze Standardversion.")
            return DEFAULT_HEROVERSION

        # Extrahiere die ersten 5 Zeichen für das Mapping (z.B. "GoPro")
        # In GOPRO_VERSION_MAP ist hinterlegt, welche Präfixe zu welcher Version gehören.
        version_prefix = devc_name[:PREFIX_LENGTH_DEVICE]
        return GOPRO_VERSION_MAP.get(version_prefix, DEFAULT_HEROVERSION)

    # ---------------------------------------------------------------------------------------
    def _get_stream_type(self, stream_chunk: list[KLVItem]) -> str | None:
        """
        Identifiziert den FourCC-Typ eines Datenstroms aus einem STRM-Block.
        In der Regel ist dies das letzte KLV-Element im Block.

        :param stream_chunk: (list[KLVItem]) Die Liste der Items innerhalb eines STRM-Blocks.
        :return: (str | None) Der FourCC-Code des Streams oder None, wenn nicht identifizierbar.
        """
        if not stream_chunk:
            if self.verbose:
                log_to_callback(Tag.WARN, "Leerer Stream-Chunk übergeben. Typ kann nicht bestimmt werden.")
            return None

        # Wir nehmen das letzte Item im Chunk als Referenz für den Typ
        last_item: KLVItem = stream_chunk[-1]

        # Wenn das letzte Item selbst ein Container ist, schauen wir tiefer hinein
        if isinstance(last_item.value, list):
            if len(last_item.value) > 0:
                found_type = last_item.value[-1].fourCC
                if self.verbose:
                    log_to_callback(Tag.STATUS, f"Stream-Typ in verschachteltem Container gefunden: {found_type}")
                return found_type

            if self.verbose:
                log_to_callback(Tag.WARN, "Verschachtelter Container im Stream ist leer.")
            return None

        # Standardfall: Die FourCC des Items selbst ist der Typ
        if self.verbose:
            log_to_callback(Tag.STATUS, f"Stream-Typ identifiziert: {last_item.fourCC}")

        return last_item.fourCC

    # ---------------------------------------------------------------------------------------
    def _process_single_devc_block(self, devc_items: list[KLVItem]) -> DEVCBlock | None:
        """Verarbeitet einen einzelnen DEVC-Block und ist jetzt eine private Hilfsmethode.
        
        :param devc_items: (list[KLVItem]) Beschreibung von devc_items.
        :return: (DEVCBlock | None) Beschreibung des Rückgabewerts.
        """

        # Nur fortfahren, wenn das Element eine Liste vom KLVItem ist
        if not isinstance(devc_items, list):
            # Optional: Warnung ausgeben und das fehlerhafte Element überspringen
            if self.verbose:
                log_to_callback(Tag.STATUS, 'KLV: DEVC Block', f"Warnung: Überspringe Element, das keine Liste von KLVItem ist: {str(devc_items)[:50]}")
            return None

        devc_id: Any = None
        devc_name: Any = None
        devc_version: int = DEFAULT_HEROVERSION
        attributes: dict[str, KLVItem] = {}
        streams: dict[str, list[STRMBlock]] = defaultdict(list)

        # Iteriere über alle Items im DEVC-Block und sortiere sie
        for item in devc_items:
            if item.fourCC == FOURCC_DVID:
                devc_id = self.parser.parse_value(item)
            elif item.fourCC == FOURCC_DVNM:
                devc_name = self.parser.parse_value(item)
                devc_version = self._process_version_devc_block(devc_name)
            elif item.fourCC == FOURCC_STRM:
                # Hier ist der entscheidende Punkt: Der Wert eines STRM-Items ist
                # eine Liste weiterer KLV-Items (ein "Chunk").
                if isinstance(item.value, list):
                    strm_chunk = item.value
                    # Hole den Stream-Typ (FourCC), der im Chunk enthalten ist.
                    strm_type = self._get_stream_type(strm_chunk)

                    if strm_type:
                        # Verarbeite den Chunk mit der Hilfsfunktion
                        strm_block = self._process_strm_chunk(strm_type, strm_chunk)
                        # Füge das verarbeitete Objekt zur Liste für diesen Stream-Typ hinzu
                        streams[strm_type].append(strm_block)
            else:
                # Sammle alle anderen Items als Attribute
                attributes[item.fourCC] = item

        return DEVCBlock(
            devc_id=devc_id,
            devc_name=devc_name,
            devc_version=devc_version,
            attributes=attributes,
            streams=streams
        )

    # ---------------------------------------------------------------------------------------
    def _process_strm_chunk(self, fourCC: str | None, current_stream_chunk: list[KLVItem]) -> STRMBlock:
        """
        Verarbeitet einen abgeschlossenen Stream-Chunk und erstellt ein STRMBlock-Objekt.

        :param fourCC: (str | None) Der FourCC Code des Streams.
        :param current_stream_chunk: (list[KLVItem]) Eine Liste von KLVItem-Objekten aus einem STRM-Block.
        :return: (STRMBlock) Ein vollständig initialisiertes STRMBlock-Objekt.
        """
        strm_name: Any = fourCC
        strm_scal: KLVItem | None = None
        strm_type: Any = None
        strm_unit: Any = None
        new_chunk_items: list[KLVItem] = []

        # Durchsuche den Chunk nach den Metadaten-Items
        for item in current_stream_chunk:
            if item.fourCC == FOURCC_STNM:
                strm_name = self.parser.parse_value(item)
            elif item.fourCC == FOURCC_SCAL:
                strm_scal = item
            elif item.fourCC == FOURCC_TYPE:
                strm_type = self.parser.parse_value(item)
            elif item.fourCC == FOURCC_UNIT or item.fourCC == FOURCC_SIUN:
                strm_unit = self.parser.parse_value(item)
            # else:
                # Nur Items, die keine Metadaten sind, werden in die Chunks-Liste aufgenommen.
            new_chunk_items.append(item)

        chunks_list: list[list[KLVItem]] = [new_chunk_items]
        # Erstelle das typsichere STRMBlock-Objekt
        return STRMBlock(
            strm_name=strm_name,
            strm_scal=strm_scal,
            strm_type=strm_type,
            strm_unit=strm_unit,
            chunks=chunks_list
        )

    # ---------------------------------------------------------------------------------------
    def get_all_stream_types(self) -> dict[str, tuple[str | None, str | None]]:
        """Extrahiert alle eindeutigen Stream-Typen (FourCCs) und ihre Namen
        
        :return: (dict[str, tuple[str | None, str | None]]) Beschreibung des Rückgabewerts.
        """

        # Repräsentation des FourCCLabels-Typs zur besseren Lesbarkeit
        FourCCInfo = dict[str, type[Any] | str]

        # --------------------------------------------------------------------------------
        def get_fourcc_info() -> tuple[str | None, str | None]:
            """Extrahiert die beschreibenden Informationen (Beschreibung und Klassenname)
            
            :return: (tuple[str | None, str | None]) Beschreibung des Rückgabewerts.
            """

            info: FourCCInfo | None = FOURCC_METADATA_MAP.get(fourcc)

            if info is None:
                return None, None

            # 1. Beschreibung (DESC)
            desc_val = info.get(KEY_CLASS_NAME)
            desc: str | None = desc_val if isinstance(desc_val, str) else None
            if not isinstance(desc, str):
                desc = None

            # 2. Klassenname (CNAME) – Umwandlung von type-Objekt in str
            cls_val: Any = info.get(KEY_DESCRIPTION)
            cls_name: str | None = None

            if isinstance(cls_val, type):
                # Wandelt das Typ-Objekt in seinen String-Namen um
                cls_name = cls_val.__name__
            elif isinstance(cls_val, str):
                cls_name = cls_val

            return desc, cls_name

        # ---------------------------------------------------------------------------------------
        all_stream_info: dict[str, tuple[str | None, str | None]] = {}

        for devc_block in self.klvdict.values():
            if devc_block.streams:
                for fourcc, strm_block in devc_block.streams.items():
                    # 1. Funktion aufrufen, um den Rückgabewert aus FourCCLabels zu erhalten
                    fourcc_desc, _ = get_fourcc_info()

                    # 2. Zuweisung des Tupels
                    strm_name_str = str(strm_block.strm_name) if strm_block.strm_name is not None else None
                    all_stream_info[fourcc] = (strm_name_str, fourcc_desc)

        return all_stream_info


# ---------------------------------------------------------------------------------------
# KLVParser: extrahiert die tatsächlichen Werte aus einem KLVItem (Element: value)
# ---------------------------------------------------------------------------------------


# ================================================================================
# ================================================================================
class KLVParser:
    """
    Kapselt die gesamte Logik zum Parsen von KLV-Item-Werten.
    """

    # ---------------------------------------------------------------------------------------
    def parse_value(self, klvdata: KLVItem, scal_item: KLVItem | None = None, stype: str | list[str] | None = None) -> Any:
        """
        Der Haupt-Parser, der Werte aus einem KLVItem extrahiert.

        :param klvdata: (KLVItem) Das KLVItem-Objekt, das die Rohdaten enthält.
        :param scal_item: (KLVItem | None) Das SCAL-KLVItem-Objekt mit den Skalierungsmetadaten.
        :param stype: (str | list[str] | None) Die geparste TYPE-Information.
        :return: (Any) Der geparste Wert oder None bei Fehlern.
        """
        if not klvdata or not klvdata.value:
            return None

        # NEUE LOGIK: Skalierungswert aus scal_item für alle Pfade extrahieren, die ihn benötigen.
        scal_value: Any = None
        if scal_item is not None:
            # Wir parsen SCAL hier einmalig, um den Wert für den komplexen Typ zu erhalten.
            scal_raw_values = self._unpack_raw_values(scal_item)

            # Bei einem einzelnen Wert im Array, diesen extrahieren, sonst die Liste/das Tupel verwenden.
            if isinstance(scal_raw_values, (tuple, list)) and len(scal_raw_values) == 1:
                scal_value = scal_raw_values[0]
            else:
                scal_value = scal_raw_values

        # 1. Fall: Handhabung von komplexen Typen (basierend auf stype_value)
        if stype:
            casted_scal: int | list[int] | None = None
            if isinstance(scal_value, int):
                casted_scal = scal_value
            elif isinstance(scal_value, list) and all(isinstance(x, int) for x in scal_value):
                casted_scal = scal_value
            return self._parse_complex_type(klvdata, stype, scal=casted_scal)

        # 2. Fall: Einfache, skalierte Typen (z.B. ACCL/GYRO)
        #   Dieser Pfad MUSS das KLVItem erhalten, da er die Logik verschachtelt ausführt.
        if scal_item is not None:
            return self._parse_simple_scaled_array(klvdata, scal_item)

        # 3. Fall: Standard-Entpackung ohne Skalierung
        raw_values = self._unpack_raw_values(klvdata)

        # 4. Fall: Rückgabe der Rohwerte (unverändert)
        if isinstance(raw_values, (tuple, list)):
            return raw_values if len(raw_values) > 1 else raw_values[0]
        return raw_values

    # ---------------------------------------------------------------------------------------
    def _parse_simple_scaled_array(self, klvdata: KLVItem, scal_item: KLVItem) -> list[tuple[float, ...]]:
        """
        Verarbeitet einfache, sich wiederholende Typen (z.B. 's', 'i') mit vorhandenem SCAL-KLVItem.
        Skalierung wird pro Sub-Element während des Entpackens angewendet.

        :param klvdata: (KLVItem) Das KLVItem, das die Rohdaten enthält (z.B. ACCL).
        :param scal_item: (KLVItem) Das KLVItem, das die Skalierungsfaktoren enthält (z.B. SCAL).
        :return: list[tuple[float, ...]]: Liste der entpackten und skalierten Daten-Tupel.
        """
        result: list[tuple[float, ...]] = []

        # 1. SCAL-Werte parsen und vorbereiten
        if not isinstance(klvdata.value, bytes):
            return result
        # Wir parsen SCAL als Rohwerte (muss hier ein numerischer Array sein)
        scal_raw_values = self._unpack_raw_values(scal_item)

        if not isinstance(scal_raw_values, (tuple, list)):
            scal_list = [scal_raw_values]
        else:
            scal_list = list(scal_raw_values)

        # 2. Metadaten für die Sub-Items ermitteln
        data_fmt_char = map_type(klvdata.type)
        if not data_fmt_char:
            # Fallback, wenn der Typ nicht gemappt werden kann
            log_to_callback(Tag.ERR, f"Fehler: Typ {klvdata.type} nicht für ACCL/GYRO-Skalierung gemappt.")
            return result

        # Größe des einzelnen Sub-Elements (z.B. 2 Bytes für 's')
        sub_element_size = struct.calcsize(data_fmt_char)

        # Anzahl der Sub-Elemente pro Wiederholung (z.B. 3 für X, Y, Z)
        sub_element_count = int(klvdata.size / sub_element_size)

        # 3. Iteration: Über jede Wiederholung (r) und jedes Sub-Element (x)
        for r in range(klvdata.repeat):
            data_tuple = []
            repeat_offset = r * klvdata.size

            for x in range(sub_element_count):
                sub_offset = x * sub_element_size

                # Sub-Chunk slicen
                chunk = klvdata.value[repeat_offset + sub_offset: repeat_offset + sub_offset + sub_element_size]

                if not chunk:
                    break

                # Entpacken des Rohwerts (z.B. signed short)
                raw_data_item = struct.unpack(BIG_ENDIAN_PREFIX + data_fmt_char, chunk)[0]

                # Skalierungsfaktor ermitteln (Zyklisches Lesen, falls SCAL nur einen oder zwei Faktoren hat)
                scale_factor = float(scal_list[x % len(scal_list)])

                # Skalierung anwenden
                if scale_factor == 0:
                    data_item = float(raw_data_item)
                else:
                    data_item = float(raw_data_item) / scale_factor

                data_tuple.append(data_item)

            # data_tuple ist jetzt ein Tupel der skalierten X, Y, Z Werte
            result.append(tuple(data_tuple))

        return result

    # ---------------------------------------------------------------------------------------
    def _parse_complex_type(self, item: KLVItem, sstype: str | list[str], scal: int | list[int] | None = None) -> list[list[Any] | tuple[Any, ...]]:
        """Verarbeitet komplexe Typen (definiert durch ein TYPE-Item).
        
        :param item: (KLVItem) Beschreibung von item.
        :param sstype: (str | list[str]) Beschreibung von sstype.
        :param scal: (int | list[int] | None) Beschreibung von scal.
        :return: (list[list[Any] | tuple[Any, ...]]) Beschreibung des Rückgabewerts.
        """

        result: list[list[Any]] = []
        if not isinstance(item.value, bytes):
            return result

        parsed_types = list(sstype) if isinstance(sstype, str) else sstype

        for r in range(item.repeat):
            offset = r * item.size
            data_tuple = []
            sub_off = 0
            for type_char in parsed_types:
                # Hier gehst du davon aus, dass die Mappings zur Verfügung stehen
                sub_stype_char = map_type(type_char.encode(ENCODING_UTF8))
                if not sub_stype_char:
                    continue
                sub_size = map_size(sub_stype_char)

                if sub_size == 0:  # Unerwarteter Typ oder Größe
                    continue

                chunk = item.value[offset + sub_off: offset + sub_off + sub_size]
                if not chunk:
                    break

                unpacked_val = struct.unpack(BIG_ENDIAN_PREFIX + sub_stype_char, chunk)[0]
                data_tuple.append(unpacked_val)
                sub_off += sub_size

            # Skalierung auf komplexe Typen anwenden
            if scal:
                scaled_tuple = self._apply_scaling(tuple(data_tuple), scal)
                data_tuple = list(scaled_tuple)

            result.append(data_tuple)
        return result

    # ---------------------------------------------------------------------------------------
    @staticmethod
    def _apply_scaling(values: tuple[Any, ...], scal: int | list[int] | None) -> tuple[float, ...]:
        """Wendet einen Skalierungsfaktor auf eine Liste von Werten an.
        
        :param values: (tuple[Any, ...]) Beschreibung von values.
        :param scal: (int | list[int] | None) Beschreibung von scal.
        :return: (tuple[float, ...]) Beschreibung des Rückgabewerts.
        """

        if scal is None:
            return tuple(float(v) for v in values)

        if isinstance(scal, int):
            scale_factor = float(scal)
            if scale_factor == 0:
                return tuple(float(v) for v in values)
            return tuple(float(v) / scale_factor for v in values)
        # scal ist eine Liste
        result = []
        for idx, val in enumerate(values):
            scale_factor = float(scal[idx % len(scal)])
            if scale_factor == 0:
                result.append(float(val))
            else:
                result.append(float(val) / scale_factor)
        return tuple(result)

    # ---------------------------------------------------------------------------------------
    @staticmethod
    def _unpack_raw_values(item: KLVItem) -> str | int | float | list[Any]:
        """
        Entpackt rohe Byte-Werte basierend auf dem Typ und der Wiederholung.

        :param item: Das KLV-Element, dessen Wert entpackt werden soll.
        :type item: KLVItem
        :return: Der entpackte Wert als String, Zahl oder Liste von Werten.
        :rtype: str | int | float | list[Any]
        """

        # --------------------------------------------------------------------------------
        def decode_value(value: Any) -> str:
            """Hilfsfunktion zum sicheren Dekodieren von Byte-Werten.

            :param value: Der zu dekodierende Wert (erwartet bytes oder None).
            :type value: Any
            :return: Der dekodierte und bereinigte String.
            :rtype: str
            """
            if value is not None and isinstance(value, bytes):
                return value.decode(ENCODING_UTF8, errors="replace").strip("\0")
            return ""

        if not isinstance(item.value, bytes):
            return item.value

        # Stelle sicher, dass der Typ ein bytes ist
        fmt_char: str | None = map_type(item.type)
        # Fallback für unbekannte Typen (z.B. komplexe oder Strings)
        if not fmt_char:
            return decode_value(item.value)
            # return item.value.decode(ENCODING_UTF8, errors="replace").strip("\0")

        # Überprüfe, ob es sich um einen String-Typ mit Längenangabe handelt (z.B. '4s')
        if fmt_char.endswith(STRING_TYPE_SUFFIX):
            # Dekodierung der gesamten Byte-Sequenz
            return decode_value(item.value)
            # return item.value.decode(ENCODING_UTF8, errors="replace").strip("\0")

        # Sonderfall: 'c' (char) wird zu Bytes entpackt, muss aber als String zurückgegeben werden
        if fmt_char == CHAR_TYPE_CODE:
            # NEUE LOGIK: Array von festen Strings (wie z.B. 9x3 Byte Units)
            if item.repeat > 1:
                result: list[str] = []
                elem_size: int = item.size  # Die Größe eines einzelnen Strings (hier 3)
                offset: int = 0

                # Iteriere durch alle Wiederholungen
                for _ in range(item.repeat):
                    chunk = item.value[offset:offset + elem_size]
                    if not chunk:
                        break

                    # Dekodieren des einzelnen Strings und Strippen von Nullbytes
                    decoded_string = decode_value(chunk)
                    # decoded_string = chunk.decode(ENCODING_UTF8, errors="replace").strip("\0")
                    result.append(decoded_string)
                    offset += elem_size

                # Gibt eine Liste von Strings zurück (z.B. ['deg', 'deg', 'm', ...])
                return result

            # Fall: Einzelnes Zeichen/String (repeat = 1)
            # Wenn item.size > 1 ist, wird der gesamte Stream als ein String behandelt (z.B. 'STMP' als Name)
            return decode_value(item.value)
            # return item.value.decode(ENCODING_UTF8, errors="replace").strip("\0")

        # Standard-Fall: numerische Typen
        if fmt_char is None:
            raise ValueError(f"Ungültiger oder nicht unterstützter KLV-Typ: {item.type}")

        total_count: int = item.repeat
        fmt: str = BIG_ENDIAN_PREFIX + (fmt_char * total_count)

        try:
            # struct.unpack gibt ein Tuple zurück; wir wandeln es in eine Liste um
            unpacked_tuple: tuple[Any, ...] = struct.unpack(fmt, item.value)

            # Wenn es nur ein einzelnes Element ist (repeat == 1), geben wir es direkt zurück
            if len(unpacked_tuple) == 1:
                single_value: int | float = unpacked_tuple[0]
                return single_value

            return list(unpacked_tuple)
        except struct.error:
            # Fallback bei Fehlern
            result: list[Any] = []
            elem_size = struct.calcsize(fmt_char)
            offset = 0
            single_fmt: str = BIG_ENDIAN_PREFIX + fmt_char

            for _ in range(total_count):
                chunk = item.value[offset:offset + elem_size]
                if not chunk or len(chunk) < elem_size:
                    break
                result.append(struct.unpack(single_fmt, chunk)[0])
                offset += elem_size
            return result
