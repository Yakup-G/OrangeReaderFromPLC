"""
config.py  —  Orange Pi Agent Yapılandırması
─────────────────────────────────────────────────────────────
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Union


# ═════════════════════════════════════════════
# 1. BU CIHAZIN KİMLİĞİ
# ═════════════════════════════════════════════

AGENT_ID = "CNC-01"


# ═════════════════════════════════════════════
# 2. PLC BAĞLANTI AYARLARI
# ═════════════════════════════════════════════

PLC_IP      = "192.168.250.1"   
PLC_PORT    = 9600              
PLC_TIMEOUT = 5.0               

# PROTOKOL SEÇİMİ - BURAYI DEĞİŞTİR
PROTOCOL = "UDP"          # "TCP" veya "UDP" yazın

# FINS Node Ayarları
PLC_FINS_NODE    = 1
CLIENT_FINS_NODE = 33


# ═════════════════════════════════════════════
# 3. SUNUCU AYARLARI
# ═════════════════════════════════════════════
SERVER_URL = "http://127.0.0.1:8080"   # Fake sunucuya yönlendir
# SERVER_URL     = "http://192.168.1.100:8080"
SERVER_API_KEY = "gizli-anahtar-buraya"


# ═════════════════════════════════════════════
# 4. ZAMANLAMA ve LOG
# ═════════════════════════════════════════════

READ_INTERVAL_SEC   = 5
RECONNECT_DELAY_SEC = 5.0
LOG_FILE            = "logs/agent.log"
LOG_LEVEL           = "INFO"


# ═════════════════════════════════════════════
# 5. FINS TAG TANIMLARI
# ═════════════════════════════════════════════

@dataclass
class FinsTag:
    label:        str
    memory_area:  str
    address:      Union[int, str]        # Bit için: "50.0" string
    data_type:    str = "ui"
    scale:        float = 1.0
    unit:         str = ""


TAGS: List[FinsTag] = [
    FinsTag(label="Çalışma Durumu", memory_area="d", address=101, data_type="ui"),
    FinsTag(label="Arıza Kodu",     memory_area="d", address=200, data_type="ui"),
    FinsTag(label="Çalışma Saati",  memory_area="d", address=100, data_type="ui", unit="hours"),
    FinsTag(label="Sıcaklık",       memory_area="d", address=300, data_type="ui", scale=0.1, unit="°C"),
    FinsTag(label="Devir",          memory_area="d", address=400, data_type="ui", unit="rpm"),
]


# ═════════════════════════════════════════════
# 6. ARIZA KOD TABLOSU
# ═════════════════════════════════════════════

FAULT_CODES = {
    0:   None,
    1:   "Aşırı ısınma",
    2:   "Aşırı yük",
    3:   "Acil durdurma aktif",
    4:   "Sensör hatası",
    5:   "Hidrolik basınç düşük",
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
    protocol:    str = "UDP"   # "TCP" veya "UDP"
