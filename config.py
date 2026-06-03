"""
config.py  —  Orange Pi Agent Yapılandırması
─────────────────────────────────────────────────────────────
Her Orange Pi'da SADECE bu dosyayı düzenliyorsun.
Başka hiçbir dosyaya dokunmana gerek yok.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


# ═════════════════════════════════════════════
# 1. BU CIHAZIN KİMLİĞİ
# ═════════════════════════════════════════════

# Dashboard'da hangi makine olarak görünecek
AGENT_ID = "CNC-01"


# ═════════════════════════════════════════════
# 2. PLC BAĞLANTI AYARLARI  (eth1 portu)
# ═════════════════════════════════════════════

PLC_IP      = "192.168.250.1"   # Senin PLC'nin IP adresi
PLC_PORT    = 9600              # Omron FINS/TCP varsayılan portu
PLC_TIMEOUT = 5.0               # Bağlantı zaman aşımı (saniye)

# Omron FINS Node adresleri
# PLC'nin FINS node numarası — genelde 0 veya PLC'nin son IP oktet'i
# Örnek: 192.168.250.1 → node = 1
PLC_FINS_NODE    = 1    # PLC node numarası
CLIENT_FINS_NODE = 33    # Bu Orange Pi'nin node numarası (herhangi bir boş numara)


# ═════════════════════════════════════════════
# 3. SUNUCU AYARLARI  (eth0 portu)
# ═════════════════════════════════════════════

SERVER_URL     = "http://192.168.1.100:8080"  # Dashboard sunucusunun adresi
SERVER_API_KEY = "gizli-anahtar-buraya"       # app.py'deki AGENT_API_KEY ile aynı olmalı


# ═════════════════════════════════════════════
# 4. ZAMANLAMA
# ═════════════════════════════════════════════

READ_INTERVAL_SEC   = 5    # Kaç saniyede bir PLC okunacak
RECONNECT_DELAY_SEC = 5.0  # Bağlantı kopunca kaç saniye beklenecek
LOG_FILE            = "logs/agent.log"
LOG_LEVEL           = "INFO"   # DEBUG, INFO, WARNING, ERROR


# ═════════════════════════════════════════════
# 5. FINS ADRES TANIMI
#
# memory_area → Omron bellek bölgesi:
#   "d"  = Data Memory  (D0, D1, D100 ...)   ← En çok kullanılan
#   "c"  = CIO / I-O    (C0, C1 ...)
#   "h"  = Holding      (H0, H1 ...)
#   "w"  = Work         (W0, W1 ...)
#
# address → Adres numarası (D100 → 100)
#
# data_type → Verinin tipi:
#   "ui"  = Unsigned INT    0..65535        (sayaç, saat gibi)
#   "i"   = Signed INT      -32768..32767
#   "udi" = Unsigned DINT   0..4294967295   (büyük sayılar)
#   "r"   = REAL            float           (sıcaklık, basınç)
#   "w"   = WORD            ham hex
#
# scale → Ham değerle çarpılacak katsayı
#   Örnek: PLC 245 gönderiyorsa ve gerçek değer 24.5°C ise → scale=0.1
#
# label → Dashboard'da görünecek isim
# unit  → Birimi (gösterim için)
# ═════════════════════════════════════════════

@dataclass
class FinsTag:
    label:       str           # Dashboard'da görünecek isim
    memory_area: str           # "d", "c", "h", "w"
    address:     int           # Adres numarası
    data_type:   str = "ui"    # Veri tipi
    scale:       float = 1.0   # Çarpan
    unit:        str  = ""     # Birimi


# ─────────────────────────────────────────────
# OKUMAK İSTEDİĞİN FINS ADRESLERİ
#
# PLC programcısından şunları sor:
#   "Çalışma saatini hangi D adresinde tutuyorsun?"
#   "Makine açık/kapalı bitini hangi adreste tutuyorsun?"
#   "Arıza kodunu hangi adreste tutuyorsun?"
#
# Aşağıdaki adresleri kendi PLC'ne göre güncelle:
# ─────────────────────────────────────────────

TAGS: List[FinsTag] = [
    FinsTag(
        label       = "Çalışma Saati",
        memory_area = "d",       # Data Memory
        address     = 100,       # D100
        data_type   = "ui",      # 0..65535 saat
        scale       = 1.0,
        unit        = "hours",
    ),
    FinsTag(
        label       = "Çalışma Durumu",
        memory_area = "d",       # Data Memory
        address     = 101,       # D101  →  0=kapalı, 1=çalışıyor
        data_type   = "ui",
        scale       = 1.0,
        unit        = "bool",
    ),
    FinsTag(
        label       = "Arıza Kodu",
        memory_area = "d",       # Data Memory
        address     = 200,       # D200  →  0=normal, >0=arıza
        data_type   = "ui",
        scale       = 1.0,
        unit        = "code",
    ),
    # ── Opsiyonel — ihtiyacın yoksa sil ──
    FinsTag(
        label       = "Sıcaklık",
        memory_area = "d",
        address     = 300,       # D300  →  245 geliyorsa = 24.5°C
        data_type   = "ui",
        scale       = 0.1,       # PLC 10x büyük gönderiyorsa
        unit        = "°C",
    ),
    FinsTag(
        label       = "Devir",
        memory_area = "d",
        address     = 400,       # D400  →  RPM
        data_type   = "ui",
        scale       = 1.0,
        unit        = "rpm",
    ),
]


# ═════════════════════════════════════════════
# 6. ARIZA KOD TABLOSU
# PLC'nin hata kodlarını buraya ekle
# ═════════════════════════════════════════════

FAULT_CODES = {
    0:   None,                 # Normal — alarm yok
    1:   "Aşırı ısınma",
    2:   "Aşırı yük",
    3:   "Acil durdurma aktif",
    4:   "Sensör hatası",
    5:   "Hidrolik basınç düşük",
    10:  "Beklenmedik duruş",
    99:  "Genel arıza",
}


# ═════════════════════════════════════════════
# 7. İÇ YAPILAR  (değiştirme)
# ═════════════════════════════════════════════

@dataclass
class PLCConfig:
    ip:        str
    port:      int   = 9600
    timeout:   float = 5.0
    fins_node: int   = 1
    client_node: int = 2
