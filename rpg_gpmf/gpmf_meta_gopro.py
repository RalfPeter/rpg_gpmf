#!/usr/bin/env python
# ------------------------------------------------------------------------------
# 10-08-2026
# RalfPeter <ralfpeter.bergheim@gmail.com>
# https://github.com/RalfPeter/
#
# Released under GNU GENERAL PUBLIC LICENSE v3. (Use at your own risk)
# ------------------------------------------------------------------------------
#  Programm          : gpmf_meta_gopro.py
#  Version           : 2.0
#  Beschreibung      : Keine Beschreibung verfügbar.
#  Zeilen            : 1075
#  Abhängigkeiten    : cProfile, datetime, enum, functools, hashlib, json, mmap, pathlib, re, struct, typing
#  Klassen           : NoGoProError, NoGpmfError, ExtractionMethod, GPMFExtractor, GoProFile, GpmfFile, GpmfFiles
#                     GoProRenamer
# ------------------------------------------------------------------------------
#  Public Methoden:
#    GPMFExtractor                                        → Liest GPMF-Daten aus GoPro MP4-Videos oder Binärdateien.
#      gpmf_metadata()                                    → Lazy-Loading Property für die Rohdaten der ffprobe JSON-Ausgabe.
#      get_raw_telemetry(ExtractionMethod, bool, 
#                        cProfile.Profile)                → Zentrale öffentliche Methode, die alle unterschiedlichen Lese-Mechanismen verbirgt.
#
#    GoProFile                                            → Liest GPMF-Daten aus GoPro MP4-Videos oder Binärdateien.
#      data()                                             → Gibt das ermittelte GoPro-Modell zurück.
#      related_files(Path)                                → Findet alle zugehörigen Kapitel-Dateien einer GoPro-Aufnahme.
#      get_gpmf(bool, bool, cProfile.Profile)             → Keine Beschreibung.
#
#    GoProRenamer                                         → Klasse zur konsistenten Verarbeitung und Umbenennung von GoPro-Videosequenzen samt Begleitdateien.
#      rename_sequences(GoProRecordingGroups)             → Benennt GoPro-Kapitel und alle zugehörigen Begleitdateien fortlaufend um.
# ------------------------------------------------------------------------------
#  Copyright (C) 2026 <ralfpeter.bergheim@gmail.com>
# ------------------------------------------------------------------------------

import re
import struct
import mmap
import hashlib
import cProfile
import json
from enum import Enum, auto
from functools import partial
from pathlib import Path
from typing import cast, Any, Final, TypeAlias
from datetime import datetime


from rpg_utils.utils_core import log_to_callback, CallbackTag as Tag
from rpg_utils.utils_math import MathUtils
from rpg_utils.utils_datetime import DateTimeUtils, TZ_UTC
from rpg_utils.utils_string import StringUtils as Str
from rpg_gpmf.gpmf_const import GPMF_EXTENSIONS, ENCODER_GOPRO, VIDEO_EXTENSIONS
from rpg_gpmf.gpmf_ffmpeg import get_ffmpeg_service
from rpg_gpmf.gpmf_meta_video import VideoFile, FFPROBE_JSON_ARGS
from rpg_gpmf.gpmf_klv_schema import GPSData, BFOURCC_DEVC
from rpg_gpmf.gpmf_klv import KLVItemList, KLVItem, ConsolidatedDEVCBlock
from rpg_gpmf.gpmf_klv_points import GPSItems


# ===========================================================================
# Global variables
# ===========================================================================
# ---------------------------------------------------------------------------
PATTERN = r"G([HXP]|OPR)(\d{2})?(\d{4}).*(MP4|mp4)"
# -------------------------------------------------------------------------------------------
# -------------------------------------------------------------------------------------------
# Konstanten für den MP4-Atom-Parser
# -------------------------------------------------------------------------------------------
_MOOV_READ_SIZE: int = 512 * 1024  # 512 KB für Top-Level-Atom-Header
_MOOV_TAIL_SIZE: int = 4 * 1024 * 1024  # 4 MB Tail-Suche falls moov am Ende liegt

# -------------------------------------------------------------------------------------------
# Konstanten für GoPro-spezifische Literale
# -------------------------------------------------------------------------------------------
_GOPRO_MET_HANDLER: Final[bytes] = b"GoPro MET"
_DEVC_MAX_BLOCK_SIZE: Final[int] = 1024 * 1024  # 1MB Plausibilitätslimit
_DEVC_VALID_NESTED: Final[set[bytes]] = {b"DVID", b"DVNM", b"STRM"}  # Gültige erste verschachtelte FourCCs laut GPMF-Spec:

# Konstanten für bessere Wartbarkeit
PREFIX_FORMAT: str = "{sequence_id:02d}_"

# Definition der Typen
GoProChapter: TypeAlias = tuple[Path, datetime]
GoProRecordingGroups: TypeAlias = dict[int, list[GoProChapter]]


# ================================================================================
# ================================================================================
class NoGoProError(Exception):
    
    # --------------------------------------------------------------------------------
    """--------------------------------------------------------------------------------"""

    def __init__(self, file: Path, message="Die Datei ist kein GoPro Video."):
        """Kurzbeschreibung für __init__.
        
        :param file: (Path) Beschreibung von file.
        :param message: (Any) Beschreibung von message.
        """

        self.message = message
        self.file = file
        if file:
            self.path = file.parent
            self.name = file.name
        super().__init__(message)


# ================================================================================
# ================================================================================
class NoGpmfError(Exception):
    
    # --------------------------------------------------------------------------------
    """--------------------------------------------------------------------------------"""

    def __init__(self, file: Path, message="Die Datei ist kein Gpmf.", reason: str = ""):
        """Kurzbeschreibung für __init__.
        
        :param file: (Path) Beschreibung von file.
        :param message: (Any) Beschreibung von message.
        :param reason: (str) Beschreibung von reason.
        """

        self.message: str = f"{message} ({reason})" if reason else message
        self.file = file
        if file:
            self.path = file.parent
            self.name = file.name
        super().__init__(message)


# ================================================================================
# class for enumeration of extracting method
# ================================================================================
class ExtractionMethod(Enum):
    """Definiert die verfügbaren Strategien zum Extrahieren der Telemetrie-Rohdaten."""
    ATOM = auto()        # Parsen über die MP4-Atom-Struktur (moov/trak)
    BINARY = auto()      # Direktes Suchen nach DEVC-Blöcken in der Datei
    FFMPEG = auto()      # Extraktion via externem FFmpeg-Aufruf
    FILE = auto()        # Schnelles Auslesen direkt aus einer Binärdatei


# ================================================================================
# Zentrale Basisklasse für das Handling und Extrahieren von GPMF-Daten.
# ================================================================================
class GPMFExtractor:
    """Liest GPMF-Daten aus GoPro MP4-Videos oder Binärdateien."""

    # ------------------------------------------------------------------------------------------
    def __init__(self, file: Path | str | None = None, verbose: bool = False) -> None:
        """
        Initialisiert eine GoPro-Datei und validiert den Encoder.

        :param file: (Path | str) Pfad zur Datei.
        :param verbose: (bool) Detail-Logging.
        """
        self.verbose: bool = getattr(self, "verbose", verbose)
        # raw data
        self.raw_list: list[bytes] = []
        self._raw_gpmf: bytes | None = None

        # Wenn file übergeben wurde, nutzen und auflösen
        if file is not None:
            self.file = Path(file).resolve()

        # Wenn KEIN file übergeben wurde, prüfen wir defensiv, ob eine
        # Geschwisterklasse (wie VideoFile) im selben Objekt das 'file' schon gesetzt hat.
        elif not hasattr(self, "file"):
            # Wenn weder noch: Sofortiger, sauberer Abbruch im Konstruktor!
            raise ValueError(
                "GpmfExtractor benötigt zwingend einen Dateipfad ('file'). "
                "Übergeben Sie diesen im Konstruktor oder leiten Sie die Klasse von VideoFile ab."
            )

        # Defensiv eigene ffmtools instanziieren, falls noch nicht via Mehrfachvererbung da
        if not hasattr(self, "ffmtools"):
            self.ffmtools = get_ffmpeg_service(verbose=verbose)

        # Interner Cache für GPMF-relevante Metadaten
        self._gpmf_md: dict[str, Any] = {}

    # ------------------------------------------------------------------------------------------
    @property
    def gpmf_metadata(self) -> dict[str, Any]:
        """Lazy-Loading Property für die Rohdaten der ffprobe JSON-Ausgabe.
        
        :return: (dict[str, Any]) Beschreibung des Rückgabewerts.
        """

        # Early Return löst PyCharms Type-Checker-Problem elegant
        if self._gpmf_md is not {}:
            return self._gpmf_md

        # --- DIE BRÜCKE BEI MEHRFACHVERERBUNG ---
        # Wenn wir mit einer Klasse wie VideoFile vererbt wurden, nutzen wir deren Cache!
        if hasattr(self, "md"):
            # Wir teilen uns die Daten der Geschwisterklasse, ohne ffprobe neu zu starten
            self._gpmf_md = getattr(self, "md")
            return self._gpmf_md

        # Wenn GpmfExtractor alleine steht, lädt er die Daten für sich selbst
        if not hasattr(self, "file") or not self.file or self.file.suffix in GPMF_EXTENSIONS:
            self._gpmf_md = {}
            return self._gpmf_md

        try:
            args = FFPROBE_JSON_ARGS + [str(self.file)]
            result = self.ffmtools.call_ffprobe(args)
            if result.code == 0:
                self._gpmf_md = json.loads(result.out)
                return self._gpmf_md
        except Exception as e:
            if self.verbose:
                print(f"[GpmfExtractor] ffprobe autonom fehlgeschlagen: {e}")

        self._gpmf_md = {}
        return self._gpmf_md

    # ------------------------------------------------------------------------------------------
    def _read_gpmf_track(self) -> tuple[int | None, str | None]:
        """Identifiziert den 'gpmd' Metadaten-Track in der MP4-Struktur.
        
        :return: (tuple[int | None, str | None]) Beschreibung des Rückgabewerts.
        """

        if self.ffmtools.use_json_format:
            # Greift sauber auf die eigene, abgesicherte Property zu
            streams = self.gpmf_metadata.get('streams', [])
            if not isinstance(streams, list):
                return None, None

            stream = next(
                (s for s in streams if isinstance(s, dict) and s.get('codec_tag_string') == 'gpmd'),
                None
            )
            if not stream:
                return None, None

            s_index = stream.get('index')
            if s_index is not None:
                codec_name = str(stream.get('codec_name', 'unknown'))
                codec_tag = str(stream.get('codec_tag_string', 'unknown'))
                return int(cast(str, s_index)), f"Stream {Str.safe_str(s_index)}, {codec_name} ({codec_tag})"
        else:
            # Fallback für klassischen ffprobe CLI-String-Parser
            output = self.ffmtools.call_ffprobe([str(self.file)])
            reg = re.compile(r'Stream #\d:(\d).+Data: \w+ \(gpmd', flags=re.I | re.M)
            m = reg.search(output.out)
            if m and m.group(1) is not None:
                return int(m.group(1)), str(m.group(0))

        return None, None

    # ------------------------------------------------------------------------------------------
    @staticmethod
    def _read_devc_block_size(data: bytes | mmap.mmap | memoryview, pos: int) -> int:
        """
        Ermittelt die Größe eines DEVC-Telemetrie-Blocks.

        :param data: (bytes | mmap.mmap | memoryview) Die Rohdaten.
        :param pos: (int) Startposition im Puffer.
        :return: (int) Blockgröße in Bytes oder 0 bei Ungültigkeit.
        """
        if pos + 8 > len(data):
            return 0

        fourcc, typec, size, repeat = struct.unpack_from(">4sBBH", data, pos)

        if fourcc != BFOURCC_DEVC or typec != 0x00 or size not in (1, 2):
            return 0

        payload_len = MathUtils.ceil4(size * repeat)
        block_size = 8 + payload_len

        if payload_len < 0 or block_size <= 8 or pos + block_size > len(data):
            return 0

        if block_size > _DEVC_MAX_BLOCK_SIZE:
            return 0

        nested_pos = pos + 8
        if nested_pos + 4 <= len(data):
            if data[nested_pos:nested_pos + 4] not in _DEVC_VALID_NESTED:
                return 0

        return block_size

    # ------------------------------------------------------------------------------------------
    @staticmethod
    def _iter_atoms(data: bytes, base: int = 0) -> list[tuple[bytes, int, int]]:
        """
        Iteriert über MP4-Atoms.

        :param data: (bytes) Rohdaten des Containers.
        :param base: (int) Absoluter Offset.
        :return: (list[tuple]) Liste aus (Typ, Offset, Größe).
        """
        result: list[tuple[bytes, int, int]] = []
        pos: int = 0
        while pos + 8 <= len(data):
            size, atom_type = struct.unpack_from('>I4s', data, pos)
            header_size: int = 8
            if size == 1:
                if pos + 16 > len(data):
                    break
                size = struct.unpack_from('>Q', data, pos + 8)[0]
                header_size = 16
            elif size == 0:
                size = len(data) - pos
            if size < header_size or pos + size > len(data):
                break
            payload_offset: int = base + pos + header_size
            payload_size: int = size - header_size
            result.append((atom_type, payload_offset, payload_size))
            pos += size
        return result

    # ------------------------------------------------------------------------------------------
    @staticmethod
    def _find_atom(atoms: list[tuple[bytes, int, int]], target: bytes) -> tuple[int, int] | None:
        """
        Sucht ein spezifisches Atom in der Liste.

        :param atoms: (list) Atom-Liste.
        :param target: (bytes) Gesuchter Typ.
        :return: (tuple | None) (Offset, Größe) oder None.
        """
        for atom_type, offset, size in atoms:
            if atom_type == target:
                return offset, size
        return None

    # ------------------------------------------------------------------------------------------
    def _parse_telemetry_chunks(self, f: Any, file_size: int) -> list[tuple[int, int]] | None:
        """
        Extrahiert Offsets der Telemetrie-Chunks aus der MP4-Struktur.

        :param f: (file object) Geöffnete Datei.
        :param file_size: (int) Dateigröße.
        :return: (list[tuple] | None) Liste von (Offset, Größe).
        """

        # --------------------------------------------------------------------------------
        def read_payload(offset: int, size: int) -> bytes:
            """Kurzbeschreibung für read_payload.
            
            :param offset: (int) Beschreibung von offset.
            :param size: (int) Beschreibung von size.
            :return: (bytes) Beschreibung des Rückgabewerts.
            """

            f.seek(offset)
            return f.read(size)

        # --------------------------------------------------------------------------------
        def find_moov() -> tuple[int, int] | None:
            """Kurzbeschreibung für find_moov.
            
            :return: (tuple[int, int] | None) Beschreibung des Rückgabewerts.
            """

            pos = 0
            while pos < file_size:
                f.seek(pos)
                header = f.read(8)
                if len(header) < 8:
                    break
                size, atom_type = struct.unpack_from('>I4s', header, 0)
                header_size = 8
                if size == 1:
                    ext = f.read(8)
                    if len(ext) < 8:
                        break
                    size = struct.unpack_from('>Q', ext, 0)[0]
                    header_size = 16
                elif size == 0:
                    size = file_size - pos
                if size < header_size:
                    break
                if atom_type == b'moov':
                    return pos + header_size, size - header_size
                pos += size
            return None

        try:
            moov_res = find_moov()
            if not moov_res:
                return None
            m_off, m_size = moov_res
            moov_data = read_payload(m_off, m_size)
            trak_atoms = [a for a in self._iter_atoms(moov_data, m_off) if a[0] == b'trak']

            for _, t_off, t_size in trak_atoms:
                trak_data = read_payload(t_off, t_size)
                trak_children = self._iter_atoms(trak_data, t_off)
                mdia = self._find_atom(trak_children, b'mdia')
                if not mdia: continue

                mdia_data = read_payload(*mdia)
                mdia_atoms = self._iter_atoms(mdia_data, mdia[0])
                hdlr = self._find_atom(mdia_atoms, b'hdlr')
                if not hdlr: continue

                hdlr_data = read_payload(*hdlr)
                if len(hdlr_data) < 25: continue
                if _GOPRO_MET_HANDLER not in hdlr_data[24:].rstrip(b'\x00'):
                    continue

                minf = self._find_atom(mdia_atoms, b'minf')
                if not minf: continue
                minf_data = read_payload(*minf)
                stbl = self._find_atom(self._iter_atoms(minf_data, minf[0]), b'stbl')
                if not stbl: continue

                stbl_data = read_payload(*stbl)
                stbl_atoms = self._iter_atoms(stbl_data, stbl[0])

                off_list: list[int] = []
                stco = self._find_atom(stbl_atoms, b'stco')
                co64 = self._find_atom(stbl_atoms, b'co64')
                if stco:
                    d = read_payload(*stco)
                    cnt = struct.unpack_from('>I', d, 4)[0]
                    off_list = list(struct.unpack_from(f'>{cnt}I', d, 8))
                elif co64:
                    d = read_payload(*co64)
                    cnt = struct.unpack_from('>I', d, 4)[0]
                    off_list = list(struct.unpack_from(f'>{cnt}Q', d, 8))

                size_list: list[int] = []
                stsz = self._find_atom(stbl_atoms, b'stsz')
                if stsz:
                    d = read_payload(*stsz)
                    def_sz = struct.unpack_from('>I', d, 4)[0]
                    cnt = struct.unpack_from('>I', d, 8)[0]
                    size_list = [def_sz] * cnt if def_sz != 0 else list(struct.unpack_from(f'>{cnt}I', d, 12))

                if off_list and size_list and len(off_list) == len(size_list):
                    return list(zip(off_list, size_list))
        except (struct.error, ValueError, OSError):
            return None
        return None

    # ------------------------------------------------------------------------------------------
    def _extract_by_devc_search(self, clean: bool, profiler: cProfile.Profile | None = None) -> list[bytes]:
        """
        Vollscan-Fallback für DEVC-Blöcke.

        :param clean: (bool) Ob Deduplizierung aktiv.
        """
        if profiler: profiler.enable()

        devc_list: list[bytes] = []
        seen: set[str] | None = set() if clean else None

        with self.file.open("rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                for m in re.finditer(BFOURCC_DEVC, mm):
                    pos = m.start()
                    size = self._read_devc_block_size(mm, pos)
                    if size == 0: continue
                    block = mm[pos: pos + size]
                    if clean and seen is not None:
                        h = hashlib.sha1(block).hexdigest()
                        if h in seen: continue
                        seen.add(h)
                    devc_list.append(block)

        if profiler:
            profiler.disable()
            profiler.print_stats(sort="cumtime")

        return devc_list

    # ------------------------------------------------------------------------------------------
    def _extract_by_atoms(self, clean: bool = True, profiler: cProfile.Profile | None = None) -> list[bytes]:
        """
        Extrahiert Telemetrie via Atom-Parser oder Vollscan-Fallback.

        :param clean: (bool) Duplikate entfernen.
        :param profiler: (cProfile.Profile | None) Optionaler Profiler.
        """
        if profiler: profiler.enable()

        devc_lists: list[bytes] = []
        seen: set[str] | None = set() if clean else None
        file_size: int = self.file.stat().st_size

        with self.file.open("rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                chunks = self._parse_telemetry_chunks(f, file_size)
                if chunks:
                    for c_off, c_size in chunks:
                        region = mm[c_off: min(c_off + c_size, file_size)]
                        for m in re.finditer(BFOURCC_DEVC, region):
                            pos = m.start()
                            size = self._read_devc_block_size(region, pos)
                            if size == 0: continue
                            block = region[pos: pos + size]
                            if clean and seen is not None:
                                h = hashlib.sha1(block).hexdigest()
                                if h in seen: continue
                                seen.add(h)
                            devc_lists.append(block)

        if profiler:
            profiler.disable()
            profiler.print_stats(sort="cumtime")

        return devc_lists

    # ------------------------------------------------------------------------------------------
    def _read_gpmf_raw(self, track: int) -> bytes | None:
        """
        Extrahiert den rohen GPMF-Stream eines Tracks via ffmpeg.

        :param track: (int) Der Stream-Index.
        :return: (bytes | None) Die rohen Daten.
        """
        args = ['-y', '-i', str(self.file), '-codec', 'copy', '-map', f'0:{track}', '-f', 'rawvideo', '-']
        result = self.ffmtools.call_ffmpeg(args)
        return result.out if result.code == 0 else None

    # ------------------------------------------------------------------------------------------
    def _extract_by_ffmpeg(self, profiler: cProfile.Profile | None = None) -> list[bytes]:
        """Extrahiert Telemetrie via FFMPEG.
        
        :param profiler: (cProfile.Profile | None) Beschreibung von profiler.
        :return: (list[bytes]) Beschreibung des Rückgabewerts.
        """

        if profiler: profiler.enable()

        # 1. Prüfen, ob der Stream existiert
        track_number, info = self._read_gpmf_track()
        if track_number is None:
            raise EOFError(f"Kein GPMF-Telemetrie-Track (gpmd) in der Datei gefunden: {self.file}")

        if self.verbose:
            print(f"[GpmfExtractor] GPMF-Stream gefunden: {Str.safe_str(info)}")

        # 2. Extraktion via FFmpeg ausführen
        metadata_raw = self._read_gpmf_raw(track_number)

        if profiler:
            profiler.disable()
            profiler.print_stats(sort="cumtime")

        return [metadata_raw] if metadata_raw else []

    # ------------------------------------------------------------------------------------------
    def _extract_from_binary_file(self, profiler: cProfile.Profile | None = None) -> list[bytes]:
        """Liest Telemetrie aus einer externen .bin-Datei.
        
        :param profiler: (cProfile.Profile | None) Beschreibung von profiler.
        :return: (list[bytes]) Beschreibung des Rückgabewerts.
        """

        if profiler: profiler.enable()

        # 1. Dynamisch nach der ersten existierenden Datei aus dem Tuple suchen
        filename: Path | None = None
        for ext in GPMF_EXTENSIONS:
            candidate = self.file.with_suffix(ext)
            if candidate.is_file():
                filename = candidate
                break

        # Wenn überhaupt keine passende Datei existiert, werfen wir den Fehler
        if filename is None:
            allowed_exts = ", ".join(GPMF_EXTENSIONS)
            raise FileNotFoundError(f"Missing telemetry file for '{self.file.name}' (tried: {allowed_exts})")

        with open(filename, 'rb') as fd:
            metadata_raw = fd.read()

        if metadata_raw[:4] != BFOURCC_DEVC:
            raise TypeError(f"Not a GPMF binary: {filename}")

        if profiler:
            profiler.disable()
            profiler.print_stats(sort="cumtime")

        return [metadata_raw] if metadata_raw else []

    # ------------------------------------------------------------------------------------------
    def get_raw_telemetry(self, method: ExtractionMethod = ExtractionMethod.ATOM, clean: bool = True, profiler: cProfile.Profile | None = None) -> None:
        """
        Zentrale öffentliche Methode, die alle unterschiedlichen Lese-Mechanismen verbirgt.

        Sucht und extrahiert die KLV-Rohdaten (DEVC-Blöcke) basierend auf der gewählten Strategie.

        :param method: (ExtractionMethod) Die zu verwendende Lese-Methode. Standard ist ExtractionMethod.BINARY_SEARCH.
        :param clean: (bool) Ob Deduplizierung aktiv.
        :param profiler: (cProfile.Profile | None) Optionaler Profiler.
        :return: None.
        :raises ValueError: Wenn eine unbekannte oder nicht unterstützte Methode übergeben wird.
        """
        # Der Dispatcher leitet den Aufruf ohne komplexe if-Strukturen an die richtige interne Methode weiter
        dispatcher = {
            ExtractionMethod.ATOM: partial(self._extract_by_atoms, clean=clean),
            ExtractionMethod.BINARY: partial(self._extract_by_devc_search, clean=clean),
            ExtractionMethod.FFMPEG: self._extract_by_ffmpeg,
            ExtractionMethod.FILE: self._extract_from_binary_file,
        }

        self.raw_list = []
        self._raw_gpmf = None

        # 1. Sofortige Validierung: Wenn die Methode nicht existiert, direkt abbrechen
        extractor = dispatcher.get(method)
        if not extractor:
            raise ValueError(f"Ungültige oder nicht unterstützte Extraktionsmethode: {method}")

        # 2. Daten extrahieren
        self.raw_list = extractor(profiler=profiler)
        self._raw_gpmf = b"".join(self.raw_list) if self.raw_list else None

        # NEU: Der neutrale Hook für alle Kindklassen
        if self._raw_gpmf:
            self._process_gpmf_data()

    # --------------------------------------------------------------------------------
    def _process_gpmf_data(self) -> None:
        """Hook-Methode für Kindklassen zur Weiterverarbeitung der Rohdaten.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        pass


# ================================================================================
# class for gopro filenaming and reading metadata
# ================================================================================
class GoProFile(VideoFile, GPMFExtractor):
    """Liest GPMF-Daten aus GoPro MP4-Videos oder Binärdateien."""

    # ------------------------------------------------------------------------------------------
    def __init__(self, goprofile: Path | str, verbose: bool = False, use_geocities: bool = True) -> None:
        """Initialisiert eine GoPro-Datei, validiert den Encoder und lädt Basiseigenschaften.

        :param goprofile: (Path | str) Pfad zur Datei.
        :param verbose: (bool) Detail-Logging.
        """
        # 1. Konstruktoren der Basisklassen sauber aufrufen
        VideoFile.__init__(self, file=goprofile, verbose=verbose, use_geocities=use_geocities)
        GPMFExtractor.__init__(self, verbose=verbose)

        # 2. GoPro-spezifische Validierung
        if self.encoder != ENCODER_GOPRO:
            raise NoGoProError(self.file)

        # 3. GoPro-Namenslogik analysieren
        match = self._is_valid_filepath(self.name)
        # self.meta.model = self._read_model()

        if match:
            letter: str = str(match.group(1))
            seq = match.group(2)
            rec = match.group(3)

            self.letter = letter
            self.sequence = int(seq) if seq else 1
            self.recording = int(rec)
            self.encoding = self._is_valid_letter(letter)
            self.basename = f"G{letter}{seq or ''}{rec}"
            self.pattern = f"*G{letter}??{rec}*"
        else:
            self.letter = 'H' if self.encoding == 'AVC' else 'X'
            self.sequence = 1
            self.recording = 0
            self.encoding = self._is_valid_letter(self.letter)
            self.basename = f"G{self.letter}{self.sequence:02}{self.recording:04}"
            self.pattern = f"*G{self.letter}??{self.recording:04}*"

        # 4. GoPro-spezifische Weiterverarbeitungsvariablen (NICHT Teil des puren Extractors)
        self.has_gpmf: bool = False
        self.klvlist: list[KLVItem] = []
        self.klvdict: dict[tuple[int | str | None, str | None], ConsolidatedDEVCBlock] = {}
        self.gps_items: list[GPSData] = []
        self.gps_anzitems: int = 0

    # --------------------------------------------------------------------------------
    @property
    def data(self) -> bytes | None:
        """Gibt das ermittelte GoPro-Modell zurück.
        
        :return: (bytes | None) Beschreibung des Rückgabewerts.
        """

        return self._raw_gpmf if self._raw_gpmf else None

    # ------------------------------------------------------------------------------------------
    @classmethod
    def _is_valid_letter(cls, letter: str) -> str:
        """
        Ordnet den GoPro-Präfix-Buchstaben dem Encoding-Standard zu.

        :param letter: (str) Der Buchstabe aus dem Dateinamen (H, P, OPR, X).
        :return: (str) 'AVC' oder 'HEVC'.
        """
        if letter in ("H", "P", "OPR"):
            return 'AVC'
        elif letter == "X":
            return 'HEVC'
        else:
            raise ValueError(f"Unknown encoding letter {letter}")

    # ------------------------------------------------------------------------------------------
    @classmethod
    def _is_valid_filepath(cls, filename: str) -> re.Match | None:
        """
        Prüft, ob der Dateiname dem GoPro-Muster entspricht.

        :param filename: (str) Der zu prüfende Dateiname.
        :return: (re.Match | None) Das Match-Objekt oder None.
        """
        return re.search(PATTERN, filename)

    # ------------------------------------------------------------------------------------------
    def related_files(self, directory: Path) -> list[Path]:
        """
        Findet alle zugehörigen Kapitel-Dateien einer GoPro-Aufnahme.

        :param directory: (Path) Das zu durchsuchende Verzeichnis.
        :return: (list[Path]) Sortierte Liste der Kapitel-Dateien.
        """
        pattern = re.compile(
            rf"G{self.letter}\d\d{self.recording:04}\.{re.escape(self.extension)}$",
            re.IGNORECASE
        )

        found = [
            p for p in directory.iterdir()
            if p.is_file() and pattern.match(p.name)
        ]
        found.sort(key=lambda p: p.name)
        return found

    # ------------------------------------------------------------------------------------------
    # Generate the list of all klv items and gps points from raw_data
    #   is called in class GpmfExtractor.get_raw_telemetry
    #   overriden method
    # ------------------------------------------------------------------------------------------
    def _process_gpmf_data(self) -> None:
        """Wird automatisch von get_raw_telemetry aufgerufen, sobald Daten bereitstehen.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        # 1. KLV-Verarbeitung triggern
        self._get_klv()

        # 2. GPSPoint-Verarbeitung triggern
        if self.klvdict:
            self._get_points()

    # ------------------------------------------------------------------------------------------
    # Generate the list of all klv items in the extracted raw data
    # ------------------------------------------------------------------------------------------
    def _get_klv(self) -> None:
        """Kurzbeschreibung für _get_klv.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        log_to_callback(Tag.STATUS, 'Generiere KLV', 'Generiere KLV-Item Liste aus den Telemetrie Daten')

        if self._raw_gpmf:
            klv = KLVItemList(self._raw_gpmf, self.verbose)
            self.klvdict = klv.create_itemdict()
            self.klvlist = klv.create_itemlist()

            if self.verbose:
                liste = klv.get_all_stream_types()
                log_to_callback(Tag.STATUS, 'KLVdict', '-')
                for typ, elem in liste.items():
                    # 'typ' ist hier der FourCC-Code (z.B. 'ACCL')
                    # 'elem' ist hier das Tupel (strm_name, fourcc_desc)
                    log_to_callback(Tag.STATUS, 'KLVdict Element', typ, elem)

    # -----------------------------------------------------------------------------
    # Generate the points
    # -----------------------------------------------------------------------------
    def _get_points(self) -> None:
        """Kurzbeschreibung für _get_points.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        log_to_callback(Tag.STATUS, f'Generiere Punkte', 'Generiere Punkte und Chunks aus der KLV-Item Liste')
        gps_parser = GPSItems(self.klvdict)

        if gps_parser:
            self.gps_items = gps_parser.parsed_items
            self.gps_anzitems = len(self.gps_items)
            # set gps_point and gps_datetime from telemetry
            dt_utc = DateTimeUtils.convert_to_timezone(dt=gps_parser.gps_dt, tz=TZ_UTC) if gps_parser.gps_dt else None
            dt_utc_lock = DateTimeUtils.convert_to_timezone(dt=gps_parser.gps_dt_lock, tz=TZ_UTC) if gps_parser.gps_dt_lock else None

            self._meta_data.gps_point = gps_parser.gps_point_lock or gps_parser.gps_point or self._meta_data.gps_point
            self._meta_data.gps_datetime = dt_utc_lock or dt_utc or self._meta_data.gps_datetime

            # falls wir Geo-Location haben (aus gpmf), ermitteln wir die timezone des Videos
            if self._meta_data.gps_point:
                tz = None
                if (geocities_service := self.geocities) is not None:
                    tz = geocities_service.get_tzinfo(latitude=self._meta_data.gps_point.latitude, longitude=self._meta_data.gps_point.longitude)

                # Nur anpassen, wenn Zeitzonen ungleich sind und alle benötigten Daten vorliegen
                if tz and tz != self._meta_data.tz and self._meta_data.gps_datetime:
                    self._meta_data.tz = tz
                    self._meta_data.creation = DateTimeUtils.convert_to_timezone(dt=self._meta_data.gps_datetime, tz=self._meta_data.tz)

    # -----------------------------------------------------------------------------
    def get_gpmf(self, binary: bool = False, clean: bool = True, profiler: cProfile.Profile | None = None) -> bool:

        """Kurzbeschreibung für get_gpmf.
        
        :param binary: (bool) Beschreibung von binary.
        :param clean: (bool) Beschreibung von clean.
        :param profiler: (cProfile.Profile | None) Beschreibung von profiler.
        :return: (bool) Beschreibung des Rückgabewerts.
        """

        msg_prefix = 'Lese Telemetrie'
        self.has_gpmf = False

        if not binary:
            try:
                self.get_raw_telemetry(method=ExtractionMethod.ATOM, clean=clean, profiler=profiler)
                if not self._raw_gpmf:
                    self.get_raw_telemetry(method=ExtractionMethod.BINARY, clean=clean, profiler=profiler)
                    if not self._raw_gpmf:
                        self.get_raw_telemetry(method=ExtractionMethod.FFMPEG, clean=clean, profiler=profiler)
                        if not self._raw_gpmf:
                            return False
            except EOFError:
                log_to_callback(Tag.ERR, msg_prefix, 'keine Telemetrie Daten vorhanden')
                return False
        else:
            try:
                self.get_raw_telemetry(method=ExtractionMethod.FILE, clean=clean, profiler=profiler)
            except EOFError:
                log_to_callback(Tag.ERR, msg_prefix, 'keine Telemetrie Daten vorhanden')
                return False

        self.has_gpmf = True
        return self.has_gpmf


# ================================================================================
# GPX file from binary gpmf file
# ================================================================================
class GpmfFile(GPMFExtractor):
    """Liest und verwaltet GPMF-Daten direkt aus reinen Binär- oder .gpmf-Dateien."""

    # -------------------------------------------------------------------------------------------
    def __init__(self, file: Path | str, verbose: bool = False) -> None:
        """Initialisiert die GPMF-Datei und validiert deren Struktur.

        :param file: (Path | str) Pfad zur binären GPMF-Datei.
        :param verbose: (bool) Detail-Logging aktivieren.
        """
        # 1. Datei-Infrastruktur vorbereiten
        self.file: Path = Path(file).resolve()
        if not (self.file.exists() and self.file.is_file()):
            raise ValueError(f"Nicht gefunden oder keine Datei: {self.file.name}")

        self.name: str = self.file.name
        self.path: Path = self.file.parent
        self.extension: str = self.file.suffix

        if self.extension not in GPMF_EXTENSIONS:
            raise NoGpmfError(self.file, reason=f"Falsche Extension: {self.extension}")

        # 2. Basisklasse initialisieren (Nutzt die getattr-Absicherung für verbose)
        self.verbose: bool = verbose
        GPMFExtractor.__init__(self, verbose=verbose)

        # 4. Struktur-Validierung (Prüft nur die ersten 4 Bytes, ohne alles einzulesen)
        if not self._has_valid_devc_header():
            raise NoGpmfError(self.file, reason="Kein gültiger 'DEVC' Header gefunden")

    # -------------------------------------------------------------------------------------------
    def _has_valid_devc_header(self) -> bool:
        """Prüft defensiv die ersten 4 Bytes der Datei auf das DEVC FourCC-Muster.
        
        :return: (bool) Beschreibung des Rückgabewerts.
        """

        try:
            with open(self.file, 'rb') as fd:
                header = fd.read(4)
            return header == BFOURCC_DEVC
        except OSError:
            return False

    # ------------------------------------------------------------------------------------------
    # Generate the list of all klv items in the extracted raw data
    # ------------------------------------------------------------------------------------------
    def _get_klv(self) -> None:
        """Kurzbeschreibung für _get_klv.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        log_to_callback(Tag.STATUS, 'Generiere KLV', 'Generiere KLV-Item Liste aus den Telemetrie Daten')

        if self._raw_gpmf:
            klv = KLVItemList(self._raw_gpmf, self.verbose)
            self.klvdict = klv.create_itemdict()
            self.klvlist = klv.create_itemlist()

            if self.verbose:
                liste = klv.get_all_stream_types()
                log_to_callback(Tag.STATUS, 'KLVdict', '-')
                for typ, elem in liste.items():
                    # 'typ' ist hier der FourCC-Code (z.B. 'ACCL')
                    # 'elem' ist hier das Tupel (strm_name, fourcc_desc)
                    log_to_callback(Tag.STATUS, 'KLVdict Element', typ, elem)

    # -----------------------------------------------------------------------------
    # Generate the points
    # -----------------------------------------------------------------------------
    def _get_points(self) -> None:
        """Kurzbeschreibung für _get_points.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        log_to_callback(Tag.STATUS, f'Generiere Punkte', 'Generiere Punkte und Chunks aus der KLV-Item Liste')
        gps_parser = GPSItems(self.klvdict)

        if gps_parser:
            self.gps_items = gps_parser.parsed_items
            self.gps_anzitems = len(self.gps_items)

    # -------------------------------------------------------------------------------------------
    def _process_gpmf_data(self) -> None:
        """Hook-Methode des GPMFExtractors.
        
        :return: (None) Beschreibung des Rückgabewerts.
        """

        # 1. KLV-Verarbeitung triggern
        if self.verbose:
            log_to_callback(Tag.STATUS, 'Generiere KLV', 'Generiere KLV-Item Liste aus den Telemetrie Daten')
        self._get_klv()

        # 2. GPSPoint-Verarbeitung triggern
        if self.verbose:
            log_to_callback(Tag.STATUS, 'Generiere KLV', 'Generiere KLV-Item Liste aus den Telemetrie Daten')
        if self.klvdict:
            self._get_points()


# ================================================================================
# find all potential gpmf files
# ================================================================================
class GpmfFiles:
    
    # --------------------------------------------------------------------------------
    """--------------------------------------------------------------------------------"""

    def __init__(self, filepath: Path):
        """Kurzbeschreibung für __init__.
        
        :param filepath: (Path) Beschreibung von filepath.
        """

        filepath = filepath.resolve()
        if not filepath.is_dir():
            raise ValueError(f"Not a valid path {filepath}")
        self.path = filepath
        self.files = self._find_gpmf_files()

    # -------------------------------------------------------------------------------------------
    def _find_gpmf_files(self) -> list[Path]:
        """Findet alle GPMF- und BIN-Dateien im Verzeichnis durch einen einzigen Scan.
        
        :return: (list[Path]) Beschreibung des Rückgabewerts.
        """

        # 1. Einmaliger, hocheffizienter Scan des Verzeichnisses
        found_metadata = [
            f
            for f in self.path.iterdir()
            if f.is_file() and f.name.casefold().endswith(GPMF_EXTENSIONS)
        ]

        # 2. Alphabetisch nach Pfad/Dateiname sortieren
        found_metadata.sort()

        return found_metadata


# ================================================================================
# ================================================================================
class GoProRenamer:
    """Klasse zur konsistenten Verarbeitung und Umbenennung von GoPro-Videosequenzen samt Begleitdateien."""

    # --------------------------------------------------------------------------------
    def __init__(self, verbose: bool = False) -> None:
        """Funktionsbeschreibung.

        :param verbose: (bool) Verbose-Ausgabe.
        """
        self.verbose: bool = verbose

    # --------------------------------------------------------------------------------
    def rename_sequences(self, pattern_groups: GoProRecordingGroups) -> None:
        """Benennt GoPro-Kapitel und alle zugehörigen Begleitdateien fortlaufend um.

        Die Gruppen werden anhand des ältesten GPS-Datums ihrer Kapitel chronologisch
        sortiert. Jede Sequenz (Recording-ID) erhält ein eindeutiges, fortlaufendes
        Präfix (z. B. 01_). Alle zum Video gehörenden Dateien (z. B. .THM, .LRV)
        werden ebenfalls mit diesem Präfix versehen.

        :param pattern_groups: GoProRecordingGroups Dict mit {recording_id: [(filepath, gps_datetime)]}.
        """
        if not pattern_groups:
            return

        log_to_callback(Tag.STATUS)
        log_to_callback(Tag.STATUS, "Alle GoPro-Videos und zugehörige Dateien innerhalb ihrer Sequenzen umbenennen")
        log_to_callback(Tag.STATUS)

        # 1. Die Gruppen anhand des ältesten GPS-Datums ihrer Kapitel vorsortieren
        sorted_groups = sorted(
            pattern_groups.items(),
            key=lambda item: min(
                (ch[1] for ch in item[1] if ch[1]), default=datetime.max
            ),
        )

        current_sequence_id = 0

        # 2. Chronologisch durch die sortierten Sequenzen iterieren
        for recording_id, chapters in sorted_groups:
            current_sequence_id += 1
            log_to_callback(Tag.STATUS, "Sequenz", f"Verarbeite Video-Sequenz (Recording ID): {recording_id}")

            # Kapitel innerhalb der Sequenz nach dem Dateinamen sortieren (GH01, GH02...)
            sorted_chapters = sorted(chapters, key=lambda c: c[0].name)

            for old_video_file, _ in sorted_chapters:
                # Prüfen, ob die Haupt-Videodatei überhaupt existiert
                if not old_video_file.is_file() or not old_video_file.name.casefold().endswith(VIDEO_EXTENSIONS):
                    continue

                prefix = PREFIX_FORMAT.format(sequence_id=current_sequence_id)
                parent_dir = old_video_file.parent

                # Exakter Basisname ohne Extension (z.B. "20260508_114909-GH011121-Biber")
                base_name = old_video_file.stem

                # 3. Präzise Suche: Nur Dateien finden, die EXAKT mit dem Basisnamen beginnen
                # und NICHT bereits das aktuelle Sequenz-Präfix besitzen.
                matching_files = [
                    f for f in parent_dir.iterdir()
                    if f.is_file() and f.name.startswith(base_name) and not f.name.startswith(prefix)
                ]

                for oldfile in matching_files:
                    newfile = parent_dir / f"{prefix}{oldfile.name}"

                    # --- SCHRITT 1: Bereinigung echter alter Rückstände ---
                    if newfile.is_file():
                        log_to_callback(Tag.STATUS, "Bereinigung", f"Alte umbenannte Datei gelöscht: {newfile.name}")
                        newfile.unlink(missing_ok=True)

                    # --- SCHRITT 2: Umbenennen ausführen ---
                    log_to_callback(Tag.STATUS, "Umbenennen", f"Datei umbenennen von {oldfile.name} nach {newfile.name}")
                    self._rename_file_add_sequence(oldfile, newfile)

        log_to_callback(Tag.STATUS)

    # --------------------------------------------------------------------------------
    @staticmethod
    def _rename_file_add_sequence(oldfile: Path, newfile: Path) -> bool:
        """Führt die physische Umbenennung einer Datei auf dem Datenträger durch.

        Überprüft vorab, ob die Zieldatei bereits existiert, benennt die Datei um
        und protokolliert einen Befehl zur einfachen Rückgängigmachung (Undo).

        :param oldfile: Path Das Pfad-Objekt der aktuellen Quelldatei.
        :param newfile: Path Das Pfad-Objekt der gewünschten Zieldatei.
        :return: bool True, wenn das Umbenennen erfolgreich war, andernfalls False.
        """
        newfile = newfile.resolve()
        oldfile = oldfile.resolve()

        if newfile.is_file():
            log_to_callback(Tag.STATUS, "Dateifehler", f"Die Datei [{newfile.name}] existiert bereits. [{oldfile.name}] wurde nicht umbenannt.")
            return False

        try:
            oldfile.rename(newfile)
        except OSError as e:
            log_to_callback(Tag.STATUS, "Fehler", f"Fehler beim Umbenennen von {oldfile.name}: {e}")
            return False

        if newfile.is_file():
            log_to_callback(Tag.STATUS, "UNDO-RENAME", f'ren "{newfile}" "{oldfile}"')
            return True

        return False
