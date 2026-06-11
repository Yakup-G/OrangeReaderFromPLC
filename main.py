"""
main.py  —  Multi-Device PLC Agent
"""

import argparse
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone

import requests

import config
from plc_reader import PLCReader
from config import PLCConfig, TAGS, FAULT_CODES
import uuid
import subprocess

# ──────────────────────────────────────────────
# OTOMATİK BENZERSİZ AGENT ID OLUŞTURMA
# ──────────────────────────────────────────────

def get_unique_agent_id() -> str:
    """Cihazın MAC adresinden benzersiz ID oluşturur"""
    try:
        # MAC adresini al
        result = subprocess.check_output("cat /sys/class/net/$(ip route show default | awk '/default/ {print $5}')/address", shell=True, text=True).strip()
        mac = result.replace(":", "").upper()
        
        # Benzersiz ID oluştur
        agent_id = f"ORANGE-{mac[-6:]}"   # Son 6 karakter + prefix
        return agent_id
    except Exception:
        # Yedek olarak random ID
        return f"ORANGE-{str(uuid.uuid4())[:8].upper()}"


# Config'den AGENT_ID yoksa otomatik oluştur
if not hasattr(config, 'AGENT_ID') or config.AGENT_ID is None or config.AGENT_ID == "":
    config.AGENT_ID = get_unique_agent_id()
    print(f"⚡ Otomatik Agent ID oluşturuldu: {config.AGENT_ID}")

def setup_logger() -> logging.Logger:
    logger = logging.getLogger("plc_agent")
    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(message)s")
    
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    
    try:
        import os
        os.makedirs("logs", exist_ok=True)
        fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass
    return logger


LOGGER = setup_logger()


def create_payload(raw_data: dict) -> dict:
    """
    PLC'den okunan ham verileri akıllıca işleyip sunucuya uygun formata çevirir.
    """
    def get(label: str, default=0.0):
        val = raw_data.get(label)
        return default if val is None else val

    # Ham verileri al
    calisma_durumu = bool(int(get("Çalışma Durumu", 0)))
    ariza_kodu     = int(get("Arıza Kodu", 0))
    calisma_saati  = round(get("Çalışma Saati", 0.0), 1)
    sicaklik       = get("Sıcaklık")
    devir          = get("Devir")

    # ── Akıllı Status Hesaplaması ──
    if ariza_kodu != 0:
        status = "err"      # Arıza öncelikli
    elif not calisma_durumu:
        status = "off"      # Makine kapalı
    elif calisma_saati > 0:
        status = "on"       # Çalışıyor
    else:
        status = "off"

    # ── Akıllı Verimlilik Hesaplaması ──
    max_weekly_hours = 48  # Bir makinenin haftalık maksimum çalışma saati
    if status == "on" and calisma_saati > 0:
        efficiency = min(100, round((calisma_saati / max_weekly_hours) * 100))
    else:
        efficiency = 0

    # ── Ana Payload ──
    payload = {
        "id": config.AGENT_ID,
        "name": config.AGENT_NAME,
        "location": config.LOCATION,
        "status": status,
        "hours_this_week": calisma_saati,
        "total_hours": calisma_saati,           # İleride toplamı ayrı tutabiliriz
        "efficiency": efficiency,               # Dinamik hesaplandı
        "fault_code": ariza_kodu,
        "fault_message": FAULT_CODES.get(ariza_kodu),
        
        # Opsiyonel sensörler
        "temperature": round(float(sicaklik), 1) if sicaklik is not None else None,
        "rpm": int(devir) if devir is not None else None,
        
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return payload


def register_to_server() -> str:
    """
    Sunucuya kayıt isteği gönder.
    'assigned' → zaten atanmış, veri göndermeye başla
    'pending'  → admin atama yapana kadar bekle
    """
    url = f"{config.SERVER_URL}/api/agent/register"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key":    config.SERVER_API_KEY,
    }
    payload = {
        "id":     config.AGENT_ID,
        "name":   config.AGENT_NAME,
        "plc_ip": config.PLC_IP,
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        status = data.get("status", "pending")
        LOGGER.info("Kayıt durumu: %s — %s", status, data.get("message", ""))
        return status
    except Exception as exc:
        LOGGER.warning("Kayıt isteği gönderilemedi: %s — veri gönderimi başlatılıyor.", exc)
        return "assigned"   # Sunucuya ulaşılamazsa doğrudan başla


def wait_for_assignment() -> bool:
    """
    Admin atama yapana kadar her 10 saniyede bir sorgula.
    Atanınca True döner.
    """
    url = f"{config.SERVER_URL}/api/agent/register/status/{config.AGENT_ID}"
    LOGGER.info("Admin ataması bekleniyor...")
    LOGGER.info("→ Admin Paneli / Bekleyen Cihazlar sayfasından bu cihazı atayın.")

    while True:
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("status") == "assigned":
                LOGGER.info("✓ Atandı: %s", data.get("customer_name", ""))
                return True
        except Exception:
            pass
        time.sleep(10)


def send_to_server(data: dict) -> bool:
    url = f"{config.SERVER_URL}/api/agent/update"
    headers = {
        "Content-Type": "application/json",
        "X-Agent-ID": config.AGENT_ID,
        "X-API-Key": config.SERVER_API_KEY,
    }
    try:
        resp = requests.post(url, json=data, headers=headers, timeout=10)
        if resp.status_code == 200:
            LOGGER.debug("✓ Sunucuya gönderildi")
            return True
        else:
            LOGGER.warning(f"Sunucu HTTP {resp.status_code}: {resp.text[:100]}")
            return False
    except Exception as e:
        LOGGER.warning(f"Sunucuya ulaşılamadı: {e}")
        return False


def on_connection_change(is_connected: bool, at: datetime):
    event = "connected" if is_connected else "disconnected"
    status = "on" if is_connected else "off"
    
    LOGGER.info(f"{'✓' if is_connected else '✖'} PLC {event}")
    
    payload = {
        "id": config.AGENT_ID,
        "name": config.AGENT_NAME,
        "status": status,
        "event": event,
        "timestamp": at.isoformat(),
        "location": config.LOCATION
    }
    send_to_server(payload)


# ─────────────────────────────────────────────
class Agent:
    def __init__(self):
        self._stop = threading.Event()
        self._reader = PLCReader(
            config=PLCConfig(
                ip=config.PLC_IP,
                port=config.PLC_PORT,
                timeout=config.PLC_TIMEOUT,
                fins_node=config.PLC_FINS_NODE,
                client_node=config.CLIENT_FINS_NODE,
                protocol=config.PROTOCOL,
            ),
            reconnect_delay=config.RECONNECT_DELAY_SEC,
            logger=LOGGER,
            connection_listener=on_connection_change,
        )

    def run(self):
        LOGGER.info("=" * 70)
        LOGGER.info(f"🚀 Agent Başladı → {config.AGENT_ID} | {config.AGENT_NAME}")
        LOGGER.info(f"PLC: {config.PLC_IP} ({config.PROTOCOL})")
        LOGGER.info(f"Sunucu: {config.SERVER_URL}")
        LOGGER.info("=" * 70)

        # ── Sunucuya kayıt ol ──
        status = register_to_server()
        if status == "pending":
            wait_for_assignment()

        LOGGER.info("✓ Cihaz aktif — veri gönderimi başlıyor.")

        while not self._stop.is_set():
            try:
                raw = self._reader.read(TAGS)
                payload = create_payload(raw)
                
                LOGGER.info(
                    f"{config.AGENT_ID} | durum={payload['status']:4} | "
                    f"saat={payload.get('hours_this_week', 0):6.1f} | "
                    f"verim={payload.get('efficiency', 0):3}%"
                )

                send_to_server(payload)

            except Exception as e:
                LOGGER.exception("Döngü hatası")

            self._stop.wait(config.READ_INTERVAL_SEC)

        self._reader.stop()

    def stop(self):
        self._stop.set()
        self._reader.stop()


# ─────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.test:
        print("Test modu henüz güncellenmedi...")
        exit(0)

    agent = Agent()

    def signal_handler(signum, frame):
        LOGGER.info("Kapatılıyor...")
        agent.stop()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    agent.run()
