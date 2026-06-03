"""
config.py  —  Orange Pi Agent Yapılandırması
─────────────────────────────────────────────────────────────
Her Orange Pi'da SADECE bu dosyayı düzenliyorsun.
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

PLC_FINS_NODE    = 1      # PLC'nin FINS node numarası
CLIENT_FINS_NODE = 33     # Orange Pi için (boş bir numara)


# ═════════════════════════════════════════════
# 3. SUNUCU AYARLARI
# ═════════════════════════════════════════════

SERVER_URL     = "http://192.168.1.100:8080"
SERVER_API_KEY = "gizli-anahtar-buraya"       # Dashboard ile aynı olmalı


# ═════════════════════════════════════════════
# 4. ZAMANLAMA ve LOG
# ═════════════════════════════════════════════

READ_INTERVAL_SEC   = 5
RECONNECT_DELAY_SEC = 5.0
LOG_FILE            = "logs/agent.log"
LOG_LEVEL           = "INFO"   # DEBUG, INFO, WARNING, ERROR


# ═════════════════════════════════════════════
# 5. FINS TAG TANIMLARI
# ═════════════════════════════════════════════

@dataclass
class FinsTag:
    label:        str                    # Gösterilecek isim
    memory_area:  str                    # "d", "c", "w", "h"
    address:      Union[int, str]        # Normal: int → Bit: "50.0" string
    data_type:    str = "ui"             # "ui", "i", "w", "r", "b" (b = bool/bit)
    scale:        float = 1.0            # Ölçek çarpanı
    unit:         str = ""               # Birim


# ─────────────────────────────────────────────
# OKUMAK İSTEDİĞİN TAG'LER (PLC'ne göre düzenle)
# ─────────────────────────────────────────────

TAGS: List[FinsTag] = [
    # ── Temel Durum Tag'leri ──
    FinsTag(
        label       = "Çalışma Durumu",
        memory_area = "d",
        address     = 101,           # Örnek: D101
        data_type   = "ui",          # 0 = Kapalı, 1 = Çalışıyor
        scale       = 1.0,
    ),
    FinsTag(
        label       = "Arıza Kodu",
        memory_area = "d",
        address     = 200,
        data_type   = "ui",
        scale       = 1.0,
    ),
    FinsTag(
        label       = "Çalışma Saati",
        memory_area = "d",
        address     = 100,
        data_type   = "ui",
        scale       = 1.0,           # Eğer 0.1 saatlik ise scale=0.1 yap
        unit        = "hours",
    ),

    # ── Analog Değerler ──
    FinsTag(
        label       = "Sıcaklık",
        memory_area = "d",
        address     = 300,
        data_type   = "ui",
        scale       = 0.1,           # PLC 245 gönderiyorsa → 24.5°C
        unit        = "°C",
    ),
    FinsTag(
        label       = "Devir",
        memory_area = "d",
        address     = 400,
        data_type   = "ui",
        scale       = 1.0,
        unit        = "rpm",
    ),

    # ── Bit (Bool) Okumaları - Önemli! ──
    # Bit okumak için data_type="b" ve address="word.bit" şeklinde string yazılır
    # Örnek:
    # FinsTag(
    #     label       = "Motor Çalışıyor",
    #     memory_area = "c",           # veya "d", "w"
    #     address     = "50.0",        # C50.00 bitini oku
    #     data_type   = "b",
    # ),
    # FinsTag(
    #     label       = "Emniyet Kilidi",
    #     memory_area = "w",
    #     address     = "100.5",       # W100.05
    #     data_type   = "b",
    # ),
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
    10:  "Beklenmedik duruş",
    99:  "Genel arıza",
}


# ═════════════════════════════════════════════
# 7. İÇ YAPILAR (değiştirme)
# ═════════════════════════════════════════════

@dataclass
class PLCConfig:
    ip:          str
    port:        int = 9600
    timeout:     float = 5.0
    fins_node:   int = 1
    client_node: int = 33
