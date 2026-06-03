"""
config.py
─────────────────────────────────────────────────────
Orange Pi Agent yapılandırması.

Her Orange Pi'da sadece bu dosyayı düzenliyorsun:
  - Bu cihazın kimliği (AGENT_ID)
  - Bağlı olduğu PLC'nin IP'si
  - Dashboard sunucusunun adresi
  - Okunacak PLC tag listesi
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


# ─────────────────────────────────────────────
# Her Orange Pi'da değiştirmen gereken ayarlar
# ─────────────────────────────────────────────

# Bu Orange Pi'nin kimliği — dashboard'da hangi makine olarak görünecek
AGENT_ID = "CNC-01"

# Bu Orange Pi'ye bağlı PLC'nin IP adresi (eth1 — PLC portu)
PLC_IP   = "192.168.2.10"
PLC_PORT = 9600          # Omron N-Serisi varsayılan portu
PLC_TIMEOUT = 5.0        # saniye

# Dashboard/sunucunun adresi (eth0 — internet/LAN portu)
SERVER_URL     = "http://192.168.1.100:8080"   # app.py'nin çalıştığı sunucu
SERVER_API_KEY = "gizli-anahtar-buraya"        # Güvenlik için — sunucuda da aynı olmalı

# Kaç saniyede bir PLC'den veri okunacak
READ_INTERVAL_SEC = 5

# Sunucuya gönderme başarısız olursa kaç saniye beklenecek
RETRY_INTERVAL_SEC = 10

# Bağlantı kesilince kaç saniyede bir yeniden denenecek
RECONNECT_DELAY_SEC = 5.0

# Log dosyası konumu
LOG_FILE = "logs/agent.log"
LOG_LEVEL = "INFO"   # DEBUG, INFO, WARNING, ERROR


# ─────────────────────────────────────────────
# Veri sınıfları (plc_reader.py bunları kullanır)
# ─────────────────────────────────────────────

@dataclass
class PLCConfig:
    """PLC bağlantı ayarları."""
    ip:      str
    port:    int   = 9600
    timeout: float = 5.0


@dataclass
class TagDefinition:
    """
    Tek bir PLC tag tanımı.

    name        : PLC içindeki tag adı (PLC programcısından öğren)
    label       : Dashboard'da gösterilecek isim
    unit        : Birimi — "hours", "bool", "rpm", "°C", vb.
    scale       : Ham değer ile çarpılacak katsayı (genelde 1.0)
    """
    name:  str
    label: str
    unit:  str   = ""
    scale: float = 1.0


# ─────────────────────────────────────────────
# Bu Orange Pi'den okunacak tag listesi
#
# PLC programcına şu soruları sor:
#   "Makinenin çalışma saati hangi tag'de?"
#   "Makine açık/kapalı durumu hangi tag'de?"
#   "Arıza kodu hangi tag'de?"
#
# Örnek tag isimleri aşağıda — kendi PLC'ne göre güncelle
# ─────────────────────────────────────────────

TAGS: List[TagDefinition] = [
    TagDefinition(
        name  = "D100",          # PLC'deki tag adı — kendi adresine göre değiştir
        label = "Çalışma Saati",
        unit  = "hours",
        scale = 1.0,
    ),
    TagDefinition(
        name  = "M0",            # Bit — 1=çalışıyor, 0=kapalı
        label = "Çalışma Durumu",
        unit  = "bool",
        scale = 1.0,
    ),
    TagDefinition(
        name  = "D200",          # Arıza kodu — 0=normal
        label = "Arıza Kodu",
        unit  = "code",
        scale = 1.0,
    ),
    TagDefinition(
        name  = "D300",          # Opsiyonel: sıcaklık
        label = "Sıcaklık",
        unit  = "°C",
        scale = 0.1,             # Örnek: PLC 245 gönderiyorsa → 24.5°C
    ),
    TagDefinition(
        name  = "D400",          # Opsiyonel: devir
        label = "Devir",
        unit  = "rpm",
        scale = 1.0,
    ),
]


# ─────────────────────────────────────────────
# Arıza kodu → mesaj çevirisi
# PLC'nin hata kodlarını buraya ekle
# ─────────────────────────────────────────────

FAULT_CODES = {
    0:   None,                          # Normal — alarm yok
    1:   "Aşırı ısınma",
    2:   "Aşırı yük",
    3:   "Acil durdurma aktif",
    4:   "Sensör hatası",
    5:   "Hidrolik basınç düşük",
    10:  "Beklenmedik duruş",
    99:  "Genel arıza",
}
