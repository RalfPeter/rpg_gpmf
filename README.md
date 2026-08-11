# rpg_gpmf

Eine leistungsfähige, modulare Python-Framework-Suite zur Extraktion und Verarbeitung von **GoPro-Telemetriedaten (GPMF)**, Erzeugung von **GPX-Tracks**, **Geokodierung**, **Karten-Rendering**, **Video-Overlays** sowie wiederverwendbaren **PySide6-UI-Utilities**.

---

## 🏗️ Architektur & Modul-Übersicht

Das Framework **rpg-tools** stellt die zentrale Bibliothek dar, auf der Anwendungs-Suites wie **[gopro-tools](https://github.com/RalfPeter/gopro-tools)** (GUIs und CLI-Skripte) aufbauen:

  ┌───────────────────────────────────────────────────────────────────────────────────┐
  │                                    gopro-tools                                    │
  │        (Anwendungen: gui_gopro2file, gui_gopro2overlay, CLI Pipelines)            │
  └─────────────────────────────────────────┬─────────────────────────────────────────┘
                                            │  nutzt als Bibliothek
                                            ▼
  ┌─────────────────────────────────────────────────────────────────────────────────────┐
  │                                     rpg-tools                                       │
  │                              (Core Framework Suite)                                 │
  ├───────────┬───────────┬───────────┬────────────────┬───────────────────┬────────────┤
  │ rpg_gpmf  │  rpg_geo  │  rpg_gpx  │    rpg_gui     │     rpg_utils     │rpg_overlay │
  │Telemetrie │Geocoding  │GPX Tracks │ PySide6 Base   │ Shared Utilities  │ Video      │
  │GPMF KLV   │GeoNames   │Schema / IO│ Templates/Utils│ Logger/Config/Math│ Overlays   │
  └───────────┴───────────┴───────────┴────────────────┴───────────────────┴────────────┘

---

---

Kern-Modul zur Extraktion und Verarbeitung von GoPro-GPMF-Binärdaten (KLV-Parsing), Video-Metadaten-Analyse und Rohdaten-Exporten.

### Enthaltene Komponenten
* **KLV-Parser:** Dekodierung nativer GoPro-GPMF-Streams direkt aus MP4- oder GPMF-Dateien.
* **Telemetrie-Extraktor:** Extraktion und Aufbereitung von GPS-Daten, Beschleunigung (ACCL), Gyro und Temperatur.
* **Writer:** Schreiben von extrahierten Telemetrie-Punkten in GPX- und KML-Dateien.

### Installation

pip install git+[https://github.com/RalfPeter/rpg_gpmf.git](https://github.com/RalfPeter/rpg_gpmf.git)

### Verwendung

from pathlib import Path
from rpg_gpmf import GpmfFile, ExtractionMethod
from rpg_gpmf import GoProFileWrite

gpmf = GpmfFile(file=Path("GOPR0001.MP4"), verbose=True)
gpmf.get_raw_telemetry(method=ExtractionMethod.FILE, clean=False)

writer = GoProFileWrite(filepath=gpmf.file)
gpx_path = writer.write_gpx_temp(points=gpmf.gps_items)
