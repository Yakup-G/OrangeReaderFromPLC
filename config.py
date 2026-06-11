"""
config.py  —  Güncel ve Uyumlu Versiyon
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Union


# ═════════════════════════════════════════════
# 1. CİHAZ BİLGİLERİ
# ═════════════════════════════════════════════

AGENT_ID      = "CNC-01"
AGENT_NAME    = "CNC Freze Makinesi #1"
LOCATION      = "Üretim Hattı 1"


# ═════════════════════════════════════════════
# 2. PLC BAĞLANTI
# ═════════════════════════════════════════════

PLC_IP       = "192.168.250.1"
PLC_PORT     = 9600
PLC_TIMEOUT  = 5.0

PROTOCOL = "UDP"

PLC_FINS_NODE    = 1
CLIENT_FINS_NODE = 33


# ═════════════════════════════════════════════
# 3. SUNUCU
# ═════════════════════════════════════════════

SERVER_URL     = "http://192.168.1.141:8080"
SERVER_API_KEY = "gizli-anahtar-buraya"


# ═════════════════════════════════════════════
# 4. ZAMANLAMA ve AYARLAR
# ═════════════════════════════════════════════

READ_INTERVAL_SEC   = 5
RECONNECT_DELAY_SEC = 5.0
DEFAULT_EFFICIENCY  = 85          # Geçici değer (sonradan dinamik yapılabilir)

LOG_FILE  = "logs/agent.log"
LOG_LEVEL = "INFO"


# ═════════════════════════════════════════════
# 5. FINS TAG TANIMLARI (PLC'den okunacaklar)
# ═════════════════════════════════════════════

@dataclass
class FinsTag:
    label:        str
    memory_area:  str
    address:      Union[int, str]
    data_type:    str = "ui"
    scale:        float = 1.0
    unit:         str = ""


TAGS: List[FinsTag] = [
    FinsTag(label="Çalışma Durumu", memory_area="d", address=101, data_type="ui"),
    FinsTag(label="Arıza Kodu",     memory_area="d", address=200, data_type="ui"),
    FinsTag(label="Çalışma Saati",  memory_area="d", address=100, data_type="ui", scale=1.0, unit="hours"),
    FinsTag(label="Sıcaklık",       memory_area="d", address=300, data_type="ui", scale=0.1, unit="°C"),
    FinsTag(label="Devir",          memory_area="d", address=400, data_type="ui", unit="rpm"),
]


# ═════════════════════════════════════════════
# 6. ARIZA KODLARI
# ═════════════════════════════════════════════

FAULT_CODES = {
    0:   None,
    1:   "Aşırı ısınma",
    2:   "Aşırı yük",
    3:   "Acil durdurma",
    4:   "Sensör hatası",
    99:  "Genel arıza",
}


# ═════════════════════════════════════════════
# 7. İÇ YAPILAR
# ═════════════════════════════════════════════

@dataclass
class PLCConfig:
    ip:          str
    port:        int = 9600
    timeout:     float = 5.0
    fins_node:   int = 1
    client_node: int = 33
    protocol:    str = "UDP"
