"""
main.py  —  Orange Pi Agent
────────────────────────────────────────────────────────────
Görev:
  1. PLC'den tag değerlerini oku  (plc_reader.py kullanarak)
  2. Ham veriyi anlamlı duruma dönüştür
  3. Dashboard sunucusuna HTTP ile gönder
  4. Her şeyi logla, hata olsa bile çalışmaya devam et

Çalıştırma:
    python main.py

Servis olarak otomatik başlatmak için:
    sudo systemctl enable plc-agent  (kurulum scripti bunu yapar)
"""

from __future__ import annotations

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
from config import PLCConfig, TagDefinition, TAGS, FAULT_CODES


# ─────────────────────────────────────────────
# Loglama
# ─────────────────────────────────────────────

def setup_logger() -> logging.Logger:
    logger = logging.getLogger("plc_agent")
    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Konsola yaz
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Dosyaya yaz
    try:
        fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        logger.warning("Log dosyası açılamadı: %s", e)

    return logger


LOGGER = setup_logger()


# ─────────────────────────────────────────────
# Ham PLC verisini dashboard formatına çevir
# ─────────────────────────────────────────────

def interpret_data(raw: dict) -> dict:
    """
    PLC'den okunan ham tag değerlerini
    dashboard'un beklediği formata dönüştürür.

    raw örneği:
        {"D100": 1240, "M0": 1, "D200": 0, "D300": 245, "D400": 1450}

    döndürülen örnek:
        {
            "id": "CNC-01",
            "status": "on",
            "hours_this_week": 38.5,
            "total_hours": 1240,
            "efficiency": 80,
            "temperature": 24.5,
            "rpm": 1450,
            "fault_code": 0,
            "fault_message": null,
            "timestamp": "2024-01-15T09:14:00+00:00"
        }
    """

    # Tag değerlerini label'a göre bul (ölçek uygula)
    def get(label: str, default=0):
        for tag in TAGS:
            if tag.label == label and tag.name in raw:
                try:
                    return raw[tag.name] * tag.scale
                except Exception:
                    return default
        return default

    # Çalışma durumu belirle
    running    = bool(get("Çalışma Durumu", 0))
    fault_code = int(get("Arıza Kodu", 0))

    if fault_code != 0:
        status = "err"
    elif not running:
        status = "off"
    else:
        status = "on"

    # Arıza mesajı
    fault_message = FAULT_CODES.get(fault_code)

    # Çalışma saatleri
    total_hours      = round(get("Çalışma Saati", 0), 1)
    hours_this_week  = round(total_hours % config.TAGS[0].scale * 48, 1) if total_hours else 0.0

    # PLC toplam saat veriyorsa doğrudan kullan,
    # haftalık saati harici hesaplanıyorsa sunucu tarafı halleder.
    # Şimdilik toplam saati gönder, sunucu haftalık hesaplar.
    hours_this_week = total_hours  # Sunucu kümülatif farkı hesaplar

    # Verimlilik: çalışıyorsa saate göre, değilse 0
    max_weekly  = 48  # Haftalık maksimum saat — config'e de taşınabilir
    efficiency  = min(100, round((hours_this_week / max_weekly) * 100)) if running else 0

    result = {
        "id":             config.AGENT_ID,
        "status":         status,
        "hours_this_week": hours_this_week,
        "total_hours":    total_hours,
        "efficiency":     efficiency,
        "fault_code":     fault_code,
        "fault_message":  fault_message,
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "raw_tags":       raw,   # Hata ayıklama için ham veriyi de gönder
    }

    # Opsiyonel alanlar — tag varsa ekle
    temp = get("Sıcaklık", None)
    if temp is not None:
        result["temperature"] = round(temp, 1)

    rpm = get("Devir", None)
    if rpm is not None:
        result["rpm"] = int(rpm)

    return result


# ─────────────────────────────────────────────
# Sunucuya veri gönder
# ─────────────────────────────────────────────

def send_to_server(data: dict) -> bool:
    """
    Veriyi dashboard sunucusuna gönder.
    Başarılıysa True, değilse False döndürür.
    """
    url = f"{config.SERVER_URL}/api/agent/update"
    headers = {
        "Content-Type":  "application/json",
        "X-Agent-ID":    config.AGENT_ID,
        "X-API-Key":     config.SERVER_API_KEY,
    }

    try:
        resp = requests.post(
            url,
            json=data,
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            LOGGER.debug("Sunucuya gönderildi: %s", config.AGENT_ID)
            return True
        else:
            LOGGER.warning(
                "Sunucu hata döndürdü: HTTP %s — %s",
                resp.status_code,
                resp.text[:200],
            )
            return False

    except requests.exceptions.ConnectionError:
        LOGGER.warning("Sunucuya bağlanılamadı: %s", config.SERVER_URL)
        return False
    except requests.exceptions.Timeout:
        LOGGER.warning("Sunucu zaman aşımı")
        return False
    except Exception as exc:
        LOGGER.error("Gönderme hatası: %s", exc)
        return False


# ─────────────────────────────────────────────
# Bağlantı durum değişikliği bildirimi
# ─────────────────────────────────────────────

def on_connection_change(is_connected: bool, at: datetime) -> None:
    if is_connected:
        LOGGER.info("✓ PLC bağlantısı kuruldu (%s)", config.PLC_IP)
        send_to_server({
            "id":        config.AGENT_ID,
            "status":    "on",
            "event":     "connected",
            "timestamp": at.isoformat(),
        })
    else:
        LOGGER.warning("✖ PLC bağlantısı kesildi (%s)", config.PLC_IP)
        send_to_server({
            "id":        config.AGENT_ID,
            "status":    "off",
            "event":     "disconnected",
            "timestamp": at.isoformat(),
        })


# ─────────────────────────────────────────────
# Ana döngü
# ─────────────────────────────────────────────

class Agent:
    def __init__(self) -> None:
        self._stop = threading.Event()

        plc_config = PLCConfig(
            ip      = config.PLC_IP,
            port    = config.PLC_PORT,
            timeout = config.PLC_TIMEOUT,
        )

        self._reader = PLCReader(
            config              = plc_config,
            reconnect_delay     = config.RECONNECT_DELAY_SEC,
            logger              = LOGGER,
            connection_listener = on_connection_change,
        )

    def run(self) -> None:
        LOGGER.info("=" * 50)
        LOGGER.info("  Orange Pi Agent başlatıldı")
        LOGGER.info("  Kimlik    : %s", config.AGENT_ID)
        LOGGER.info("  PLC       : %s:%s", config.PLC_IP, config.PLC_PORT)
        LOGGER.info("  Sunucu    : %s", config.SERVER_URL)
        LOGGER.info("  Okuma aralığı: %ss", config.READ_INTERVAL_SEC)
        LOGGER.info("=" * 50)

        consecutive_failures = 0

        while not self._stop.is_set():
            start = time.monotonic()

            try:
                # ① PLC'den oku
                LOGGER.debug("Tag'ler okunuyor...")
                raw = self._reader.read(TAGS)
                LOGGER.debug("Ham veri: %s", raw)

                # ② Yorumla
                data = interpret_data(raw)
                LOGGER.info(
                    "%-10s │ durum=%-4s │ saat=%-6s │ verim=%%%s %s",
                    data["id"],
                    data["status"],
                    data["hours_this_week"],
                    data["efficiency"],
                    f"│ sıcaklık={data['temperature']}°C" if "temperature" in data else "",
                )

                # ③ Sunucuya gönder
                ok = send_to_server(data)
                if ok:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= 5:
                        LOGGER.error(
                            "Sunucuya art arda %d kez gönderilemedi. "
                            "Ağ bağlantısını kontrol et.",
                            consecutive_failures,
                        )

            except RuntimeError as exc:
                # PLCReader.stop() çağrıldıktan sonra oluşur
                LOGGER.info("Agent durdu: %s", exc)
                break
            except Exception as exc:
                LOGGER.exception("Beklenmedik hata: %s", exc)

            # Bir sonraki okumaya kadar bekle
            elapsed = time.monotonic() - start
            wait    = max(0.0, config.READ_INTERVAL_SEC - elapsed)
            self._stop.wait(wait)

        LOGGER.info("Agent kapatılıyor...")
        self._reader.stop()
        LOGGER.info("Agent durdu.")

    def stop(self) -> None:
        self._stop.set()
        self._reader.stop()


# ─────────────────────────────────────────────
# Başlatma + sinyal yakalama (Ctrl+C / systemd)
# ─────────────────────────────────────────────

def main() -> None:
    agent = Agent()

    def _handle_signal(signum, frame):
        LOGGER.info("Sinyal %s alındı, kapatılıyor...", signum)
        agent.stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    agent.run()


if __name__ == "__main__":
    main()
