# config.py
from dataclasses import dataclass

@dataclass
class PLCConfig:
    ip: str
    port: int = 44818  # Omron NJ/NX serisi varsayılan EtherNet/IP portu
    timeout: float = 2.0

@dataclass
class TagDefinition:
    name: str

# ─────────────────────────────────────────────────────────────────
# MERKEZ SUNUCU VE BU MAKİNENİN AYARLARI
# ─────────────────────────────────────────────────────────────────

# Verilerin gönderileceği merkez Flask sunucusunun IP adresi ve API kapısı
SERVER_URL = "http://192.168.1.100:8080/api/update_plc"

# Bu Orange Pi'ın bağlı olduğu makinenin benzersiz ID'si ve Adı
MACHINE_ID = "CNC-01"
MACHINE_NAME = "CNC Freze Tezgahı #1"

# PLC içinden okunacak küresel (global) değişkenlerin isimleri.
# Buradaki isimler Omron Sysmac Studio'daki Global Variables ile birebir aynı olmalıdır.
PLC_TAGS = [
    TagDefinition("Machine_Status"),       # Durum döndüren Tag (Örn: 'on', 'off', 'warn', 'err')
    TagDefinition("Weekly_Work_Hours"),    # Bu haftaki çalışma saati (REAL / LREAL)
    TagDefinition("Current_Efficiency"),   # Anlık verimlilik yüzdesi (INT)
    TagDefinition("Lifetime_Total_Hours")  # Makinenin toplam ömür saati (REAL / LREAL)
]