"""
main.py  —  Orange Pi Agent
────────────────────────────────────────────────────────────
1. FINS/TCP ile PLC'den veri okur (yeni PLCReader)
2. Dashboard sunucusuna HTTP ile gönderir
3. Hata olsa bile çalışmaya devam eder
4. Systemd servisi olarak otomatik başlar

Çalıştırma:
    python main.py

Test modu (PLC olmadan):
    python main.py --test
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests

import config
from plc_reader import PLCReader
from config import PLCConfig, TAGS, FAULT_CODES


# ──────────────────────────────────────────────
# Loglama
# ──────────────────────────────────────────────

def setup_logger() -> logging.Logger:
    logger = logging.getLogger("plc_agent")
    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    try:
        import os
        os.makedirs("logs", exist_ok=True)
        fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        logger.warning("Log dosyası açılamadı: %s", e)
    return logger

LOGGER = setup_logger()


# ──────────────────────────────────────────────
# Ham FINS verisini dashboard formatına çevir
# ──────────────────────────────────────────────

def interpret_data(raw: dict) -> dict:
    """
    FINS'ten okunan ham değerleri dashboard formatına çevirir.
    """
    def get(label: str, default=0.0):
        val = raw.get(label)
        return default if val is None else val

    # Temel değerler
    running     = bool(int(get("Çalışma Durumu", 0)))
    fault_code  = int(get("Arıza Kodu", 0))
    total_hours = round(get("Çalışma Saati", 0.0), 1)

    # Durum belirle
    if fault_code != 0:
        status = "err"
    elif not running:
        status = "off"
    else:
        status = "on"

    fault_message = FAULT_CODES.get(fault_code)

    # Verimlilik hesabı
    max_weekly = 48
    efficiency = min(100, round((total_hours / max_weekly) * 100)) if running and total_hours > 0 else 0

    result = {
        "id":               config.AGENT_ID,
        "name":             config.AGENT_ID,
        "status":           status,
        "hours_this_week":  total_hours,
        "total_hours":      total_hours,
        "efficiency":       efficiency,
        "fault_code":       fault_code,
        "fault_message":    fault_message,
        "timestamp":        datetime.now(timezone.utc).isoformat(),
    }

    # Opsiyonel alanlar
    temp = get("Sıcaklık", None)
    if temp is not None:
        result["temperature"] = round(float(temp), 1)

    rpm = get("Devir", None)
    if rpm is not None:
        result["rpm"] = int(rpm)

    return result


# ──────────────────────────────────────────────
# Sunucuya gönder
# ──────────────────────────────────────────────

def send_to_server(data: dict) -> bool:
    url = f"{config.SERVER_URL}/api/agent/update"
    headers = {
        "Content-Type": "application/json",
        "X-Agent-ID":   config.AGENT_ID,
        "X-API-Key":    config.SERVER_API_KEY,
    }
    try:
        resp = requests.post(url, json=data, headers=headers, timeout=10)
        if resp.status_code == 200:
            LOGGER.debug("✓ Sunucuya gönderildi")
            return True
        LOGGER.warning("Sunucu HTTP %s: %s", resp.status_code, resp.text[:200])
        return False
    except requests.exceptions.ConnectionError:
        LOGGER.warning("Sunucuya ulaşılamadı: %s", config.SERVER_URL)
    except requests.exceptions.Timeout:
        LOGGER.warning("Sunucu zaman aşımı")
    except Exception as exc:
        LOGGER.error("Gönderme hatası: %s", exc)
    return False


# ──────────────────────────────────────────────
# Bağlantı değişikliği bildirimi
# ──────────────────────────────────────────────

def on_connection_change(is_connected: bool, at: datetime) -> None:
    if is_connected:
        LOGGER.info("✓ PLC bağlandı: %s", config.PLC_IP)
        send_to_server({"id": config.AGENT_ID, "status": "on",  "event": "connected",    "timestamp": at.isoformat()})
    else:
        LOGGER.warning("✖ PLC bağlantısı kesildi: %s", config.PLC_IP)
        send_to_server({"id": config.AGENT_ID, "status": "off", "event": "disconnected", "timestamp": at.isoformat()})


# ──────────────────────────────────────────────
# Ana Agent sınıfı
# ──────────────────────────────────────────────

class Agent:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._reader = PLCReader(
            config              = PLCConfig(
                ip          = config.PLC_IP,
                port        = config.PLC_PORT,
                timeout     = config.PLC_TIMEOUT,
                fins_node   = config.PLC_FINS_NODE,
                client_node = config.CLIENT_FINS_NODE,
            ),
            reconnect_delay     = config.RECONNECT_DELAY_SEC,
            logger              = LOGGER,
            connection_listener = on_connection_change,
        )

    def run(self) -> None:
        LOGGER.info("=" * 60)
        LOGGER.info("  Orange Pi PLC Agent  [TCP FINS]")
        LOGGER.info("  Kimlik      : %s", config.AGENT_ID)
        LOGGER.info("  PLC         : %s:%s  (FINS node %s)",
                    config.PLC_IP, config.PLC_PORT, config.PLC_FINS_NODE)
        LOGGER.info("  Sunucu      : %s", config.SERVER_URL)
        LOGGER.info("  Okuma aralığı: %ss", config.READ_INTERVAL_SEC)
        LOGGER.info("  Takip edilen tag sayısı: %d", len(TAGS))
        LOGGER.info("=" * 60)

        fail_count = 0

        while not self._stop.is_set():
            t0 = time.monotonic()

            try:
                # ① PLC'den oku (yeni PLCReader)
                raw = self._reader.read(TAGS)

                # ② Yorumla
                data = interpret_data(raw)

                # ③ Logla
                extras = []
                if "temperature" in data:
                    extras.append(f"sıcaklık={data['temperature']}°C")
                if "rpm" in data:
                    extras.append(f"devir={data['rpm']}rpm")

                LOGGER.info(
                    "%-10s  durum=%-4s  saat=%-7.1f  verim=%%%d  %s",
                    data["id"], data["status"],
                    data["hours_this_week"], data["efficiency"],
                    " | ".join(extras)
                )

                if data.get("fault_message"):
                    LOGGER.warning("⚠ ARIZA: %s", data["fault_message"])

                # ④ Sunucuya gönder
                ok = send_to_server(data)
                fail_count = 0 if ok else fail_count + 1

                if fail_count >= 5:
                    LOGGER.error("Sunucuya art arda 5 kez gönderilemedi! Ağ bağlantısını kontrol edin.")

            except RuntimeError as exc:
                LOGGER.info("Döngü durdu: %s", exc)
                break
            except Exception as exc:
                LOGGER.exception("Beklenmedik hata: %s", exc)
                fail_count += 1

            # Bir sonraki okuma için bekle
            elapsed = time.monotonic() - t0
            sleep_time = max(0.0, config.READ_INTERVAL_SEC - elapsed)
            self._stop.wait(sleep_time)

        LOGGER.info("Agent kapatılıyor...")
        self._reader.stop()
        LOGGER.info("Agent durdu.")

    def stop(self) -> None:
        self._stop.set()
        if hasattr(self, '_reader'):
            self._reader.stop()


# ──────────────────────────────────────────────
# Test modu
# ──────────────────────────────────────────────

def run_test():
    LOGGER.info("TEST MODU — PLC bağlantısı test ediliyor...")
    LOGGER.info("PLC: %s:%s  FINS node: %s", config.PLC_IP, config.PLC_PORT, config.PLC_FINS_NODE)

    reader = PLCReader(
        config = PLCConfig(
            ip          = config.PLC_IP,
            port        = config.PLC_PORT,
            timeout     = config.PLC_TIMEOUT,
            fins_node   = config.PLC_FINS_NODE,
            client_node = config.CLIENT_FINS_NODE,
        ),
        reconnect_delay = 2.0,
        logger          = LOGGER,
    )

    ok = reader.test_connection()
    if ok:
        LOGGER.info("✓ PLC bağlantısı başarılı!")
        LOGGER.info("Tag okuma deneniyor...")
        try:
            raw = reader.read(TAGS)
            LOGGER.info("Okunan değerler (%d tag):", len(raw))
            for label, value in raw.items():
                unit = next((t.unit for t in TAGS if t.label == label), "")
                LOGGER.info("  %-22s = %s %s", label, value, unit)
        except Exception as exc:
            LOGGER.error("Tag okuma hatası: %s", exc)
    else:
        LOGGER.error("✖ PLC'ye bağlanılamadı!")
        LOGGER.error("Kontrol edilecek noktalar:")
        LOGGER.error("  • PLC açık ve ağa bağlı mı?")
        LOGGER.error("  • IP adresi doğru mu? → %s", config.PLC_IP)
        LOGGER.error("  • FINS Node numarası doğru mu? → %s", config.PLC_FINS_NODE)

    reader.stop()


# ──────────────────────────────────────────────
# Başlangıç
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Orange Pi PLC Agent")
    parser.add_argument("--test", action="store_true", help="PLC bağlantısını test et ve çık")
    args = parser.parse_args()

    if args.test:
        run_test()
        return

    agent = Agent()

    def _signal_handler(signum, frame):
        LOGGER.info("Sinyal alındı (%s) — kapatılıyor...", signum)
        agent.stop()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT,  _signal_handler)

    try:
        agent.run()
    except KeyboardInterrupt:
        LOGGER.info("Kullanıcı tarafından durduruldu.")
        agent.stop()


if __name__ == "__main__":
    main()
