"""
plc_reader.py  —  FINS/TCP ile Omron PLC Okuyucu
─────────────────────────────────────────────────
fins kütüphanesi v1.0.5 — TCPFinsConnection kullanır.
Bağlantı kopunca otomatik yeniden bağlanır.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from fins.tcp import TCPFinsConnection

from config import PLCConfig, FinsTag

LOGGER = logging.getLogger(__name__)


class PLCReader:

    def __init__(
        self,
        config:              PLCConfig,
        reconnect_delay:     float = 5.0,
        logger:              Optional[logging.Logger] = None,
        connection_listener: Optional[Callable[[bool, datetime], None]] = None,
    ) -> None:
        self._config              = config
        self._reconnect_delay     = max(0.5, reconnect_delay)
        self._logger              = logger or LOGGER
        self._lock                = threading.Lock()
        self._conn:               Optional[TCPFinsConnection] = None
        self._stop                = threading.Event()
        self._connection_listener = connection_listener
        self._online              = False

    def stop(self) -> None:
        self._stop.set()
        self._close()

    def read(self, tags: List[FinsTag]) -> Dict[str, object]:
        """
        Tag listesini PLC'den oku.
        Döndürülen örnek:
            {
                "Çalışma Saati":  1240.0,
                "Çalışma Durumu": 1.0,
                "Arıza Kodu":     0.0,
            }
        """
        if not tags:
            return {}

        while not self._stop.is_set():
            conn = self._ensure_connection()
            if conn is None:
                break

            try:
                values: Dict[str, object] = {}

                for tag in tags:
                    try:
                        raw = conn.read(
                            memory_area      = tag.memory_area,
                            word_address     = tag.address,
                            data_type        = tag.data_type,
                            number_of_values = 1,
                        )

                        # fins 1.0.5 liste döndürür — ilk elemanı al
                        raw_val = raw[0] if isinstance(raw, (list, tuple)) else raw

                        # bytes gelirse int'e çevir
                        if isinstance(raw_val, (bytes, bytearray)):
                            raw_val = int.from_bytes(raw_val, "big")

                        values[tag.label] = round(float(raw_val) * tag.scale, 4)

                        self._logger.debug(
                            "OK  %s[%s%d] = %s %s",
                            tag.label, tag.memory_area.upper(),
                            tag.address, values[tag.label], tag.unit,
                        )

                    except Exception as exc:
                        if self._is_conn_error(exc):
                            self._logger.warning(
                                "%s[%s%d] bağlantı hatası: %s — yeniden bağlanılıyor...",
                                tag.label, tag.memory_area.upper(), tag.address, exc,
                            )
                            self._reset()
                            break  # while döngüsü yeniden dener
                        else:
                            self._logger.warning(
                                "%s[%s%d] okunamadı: %s — atlanıyor.",
                                tag.label, tag.memory_area.upper(), tag.address, exc,
                            )
                            values[tag.label] = None
                else:
                    return values  # Tüm tag'ler başarıyla okundu

            except Exception as exc:
                self._logger.exception("Beklenmedik okuma hatası: %s", exc)
                self._reset()

        raise RuntimeError("PLCReader durduruldu.")

    def test_connection(self) -> bool:
        """Bağlantıyı test et — kurulum sırasında kullan."""
        try:
            conn = TCPFinsConnection()
            conn.dest_node_add  = self._config.fins_node
            conn.srce_node_add  = self._config.client_node
            conn.connect(self._config.ip, port=self._config.port,
                         connection_timeout=self._config.timeout)
            # D0 adresini oku — sadece bağlantı testi
            conn.read("d", 0, "ui")
            conn.fins_socket.close()
            return True
        except Exception as exc:
            self._logger.error("Bağlantı testi başarısız: %s", exc)
            return False

    # ──────────────────────────────────────────
    # Dahili metodlar
    # ──────────────────────────────────────────

    def _ensure_connection(self) -> Optional[TCPFinsConnection]:
        with self._lock:
            if self._conn is not None:
                return self._conn

        while not self._stop.is_set():
            try:
                self._logger.info(
                    "PLC'ye bağlanılıyor: %s:%s (FINS node=%s)",
                    self._config.ip, self._config.port, self._config.fins_node,
                )
                conn = TCPFinsConnection()
                conn.dest_node_add = self._config.fins_node
                conn.srce_node_add = self._config.client_node
                conn.connect(
                    self._config.ip,
                    port               = self._config.port,
                    connection_timeout = self._config.timeout,
                )

                with self._lock:
                    self._conn   = conn
                    changed      = not self._online
                    self._online = True

                if changed:
                    self._notify(True)

                self._logger.info("✓ PLC bağlantısı kuruldu: %s", self._config.ip)
                return conn

            except Exception as exc:
                self._logger.error(
                    "Bağlantı kurulamadı (%s): %s — %.1fs sonra tekrar.",
                    self._config.ip, exc, self._reconnect_delay,
                )
                self._stop.wait(self._reconnect_delay)

        return None

    def _reset(self) -> None:
        self._close()
        self._stop.wait(self._reconnect_delay)

    def _close(self) -> None:
        notify = False
        with self._lock:
            conn         = self._conn
            self._conn   = None
            if self._online:
                self._online = False
                notify       = True

        if conn is not None:
            try:
                conn.fins_socket.close()
                self._logger.info("Bağlantı kapatıldı: %s", self._config.ip)
            except Exception:
                self._logger.debug("Bağlantı kapatma hatası (sorun değil)", exc_info=True)

        if notify:
            self._notify(False)

    def _is_conn_error(self, exc: Exception) -> bool:
        if isinstance(exc, (ConnectionError, TimeoutError, OSError, BrokenPipeError)):
            return True
        msg = str(exc).lower()
        return any(k in msg for k in ("timeout", "connection", "network", "refused", "reset", "fins", "broken"))

    def _notify(self, is_connected: bool) -> None:
        if self._connection_listener is None:
            return
        try:
            self._connection_listener(is_connected, datetime.now(timezone.utc))
        except Exception:
            self._logger.exception("Listener hatası")
