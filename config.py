"""
config.py  —  Multi-Device Orange Pi PLC Agent
Her cihazda SADECE bu dosyayı düzenliyorsun.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Union

# ═════════════════════════════════════════════
# 1. CİHAZ KİMLİĞİ (HER CİHAZ İÇİN BENZERSİZ OLACAK)
# ═════════════════════════════════════════════

AGENT_ID = "CNC-01"                    # Örnek: CNC-01, PRESS-02, LINE1-ROBOT3
AGENT_NAME = "CNC Makine 01"           # Daha okunaklı isim
LOCATION = "Üretim Hattı 1"            # Opsiyonel: Konum bilgisi

# ═════════════════════════════════════════════
# 2. PLC BAĞLANTI AYARLARI
# ═════════════════════════════════════════════

PLC_IP      = "192.168.250.1"
PLC_PORT    = 9600
PLC_TIMEOUT = 5.0

PROTOCOL = "UDP"                       # "UDP" veya "TCP"

PLC_FINS_NODE    = 1
CLIENT_FINS_NODE = 33

# ═════════════════════════════════════════════
# 3. SUNUCU AYARLARI
# ═════════════════════════════════════════════

# SERVER_URL     = "http://127.0.0.1:8080"   # Test için fake server
SERVER_URL = "http://192.168.1.141:8080"
# SERVER_URL   = "http://192.168.1.100:8080"  # Gerçek sunucu

SERVER_API_KEY = "gizli-anahtar-buraya"

# ═════════════════════════════════════════════
# 4. ZAMANLAMA ve DAVRANIŞ
# ═════════════════════════════════════════════

READ_INTERVAL_SEC   = 5
RECONNECT_DELAY_SEC = 5.0
HEARTBEAT_INTERVAL_SEC = 30        # Sunucuya heartbeat gönderme aralığı
DEFAULT_EFFICIENCY = 85            # ← Ekle (geçici verim değeri)

LOG_FILE  = "logs/agent.log"
LOG_LEVEL = "INFO"                 # DEBUG / INFO / WARNING

# ═════════════════════════════════════════════
# 5. FINS TAG TANIMLARI
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
    FinsTag(label="Çalışma Saati",  memory_area="d", address=100, data_type="ui", unit="hours"),
    FinsTag(label="Sıcaklık",       memory_area="d", address=300, data_type="ui", scale=0.1, unit="°C"),
    FinsTag(label="Devir",          memory_area="d", address=400, data_type="ui", unit="rpm"),
]


# ═════════════════════════════════════════════
# 6. ARIZA KODLARI
# ═════════════════════════════════════════════

FAULT_CODES = {
    0: None,
    1: "Aşırı ısınma",
    2: "Aşırı yük",
    99: "Genel arıza",
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
