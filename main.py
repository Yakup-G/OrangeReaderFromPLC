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
    """Agent'tan sunucuya gönderilecek veriyi hazırlar"""
    def get(label: str, default=0.0):
        val = raw_data.get(label)
        return default if val is None else val

    running = bool(int(get("Çalışma Durumu", 0)))
    fault_code = int(get("Arıza Kodu", 0))
    hours = round(get("Çalışma Saati", 0.0), 1)

    if fault_code != 0:
        status = "err"
    elif not running:
        status = "off"
    else:
        status = "on"

    payload = {
        "id": config.AGENT_ID,
        "name": config.AGENT_NAME,
        "location": config.LOCATION,
        "status": status,
        "hours_this_week": hours,
        "total_hours": hours,
        "efficiency": config.DEFAULT_EFFICIENCY,   # config'ten alıyoruz
        "fault_code": fault_code,
        "fault_message": FAULT_CODES.get(fault_code),
        "temperature": round(get("Sıcaklık"), 1) if "Sıcaklık" in raw_data else None,
        "rpm": int(get("Devir")) if "Devir" in raw_data else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return payload


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
