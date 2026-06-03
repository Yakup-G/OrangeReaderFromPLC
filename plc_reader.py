"""
plc_reader.py  —  FINS/TCP ile Omron PLC Okuyucu (Client tabanlı)
──────────────────────────────────────────────────────────────
client.py'deki TCP okuma mantığı entegre edildi.
Bool (bit) okuması için özel destek eklendi.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from fins.tcp import TCPFinsConnection
import fins.fins_common

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
        Tag listesini PLC'den oku (client.py mantığı ile).
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
                        success, result, message = self._read_single_tag(conn, tag)

                        if success:
                            # Ölçekleme uygula
                            scaled_value = round(float(result) * tag.scale, 4)
                            values[tag.label] = scaled_value

                            self._logger.debug(
                                "OK  %s[%s%d] = %s %s",
                                tag.label, tag.memory_area.upper(),
                                tag.address, scaled_value, tag.unit,
                            )
                        else:
                            self._logger.warning(
                                "%s[%s%d] okunamadı: %s",
                                tag.label, tag.memory_area.upper(), tag.address, message
                            )
                            values[tag.label] = None

                    except Exception as exc:
                        if self._is_conn_error(exc):
                            self._logger.warning(
                                "%s[%s%d] bağlantı hatası: %s — yeniden bağlanılıyor...",
                                tag.label, tag.memory_area.upper(), tag.address, exc,
                            )
                            self._reset()
                            break
                        else:
                            self._logger.warning(
                                "%s[%s%d] okunamadı: %s",
                                tag.label, tag.memory_area.upper(), tag.address, exc
                            )
                            values[tag.label] = None

                else:
                    # Tüm tag'ler okundu
                    return values

            except Exception as exc:
                self._logger.exception("Beklenmedik okuma hatası: %s", exc)
                self._reset()

        raise RuntimeError("PLCReader durduruldu.")

    def _read_single_tag(self, conn: TCPFinsConnection, tag: FinsTag) -> tuple[bool, any, str]:
        """Tek bir tag'i client.py mantığı ile oku"""
        try:
            memory_area = tag.memory_area.lower()
            address_str = str(tag.address)

            # Bool (Bit) okuması için özel işlem
            if tag.data_type.lower() == 'b':
                return self._read_bit(conn, memory_area, address_str)

            # Normal okuma (word, uint, int, float vb.)
            result = conn.read(
                memory_area=memory_area,
                word_address=tag.address,
                data_type=tag.data_type.lower(),
                number_of_values=1,
            )
            raw_val = result[0] if isinstance(result, (list, tuple)) else result

            if isinstance(raw_val, (bytes, bytearray)):
                raw_val = int.from_bytes(raw_val, "big")

            return True, raw_val, "success"

        except Exception as e:
            return False, None, str(e)

    def _read_bit(self, conn: TCPFinsConnection, memory_area: str, address_str: str) -> tuple[bool, any, str]:
        """Bit (Bool) okuması - client.py'deki özel mantık"""
        try:
            if "." in address_str:
                parts = address_str.split(".")
                word_address = int(parts[0])
                bit_address = int(parts[1])
            else:
                word_address = int(address_str)
                bit_address = 0

            memory_areas = fins.fins_common.FinsPLCMemoryAreas()
            ma = memory_area.lower()

            if ma == 'w':
                read_area = memory_areas.WORK_BIT
            elif ma == 'c':
                read_area = memory_areas.CIO_BIT
            elif ma == 'd':
                read_area = memory_areas.DATA_MEMORY_BIT
            elif ma == 'h':
                read_area = memory_areas.HOLDING_BIT
            else:
                read_area = memory_areas.DATA_MEMORY_BIT

            begin_address = word_address.to_bytes(2, 'big') + bit_address.to_bytes(1, 'big')
            response = conn.memory_area_read(read_area, begin_address, 1)

            fins_response = fins.fins_common.FinsResponseFrame()
            fins_response.from_bytes(response)

            if not fins_response.end_code.startswith(b'\x00'):
                return False, None, f"End Code: {fins_response.end_code}"

            data = fins_response.text
            return True, int.from_bytes(data, 'big'), "success"

        except Exception as e:
            return False, None, str(e)

    def test_connection(self) -> bool:
        """Bağlantıyı test et"""
        try:
            conn = TCPFinsConnection()
            conn.dest_node_add = self._config.fins_node
            conn.srce_node_add = self._config.client_node
            conn.connect(self._config.ip, port=self._config.port,
                         connection_timeout=self._config.timeout)
            # Basit test okuma
            conn.read("d", 0, "ui")
            conn.fins_socket.close()
            return True
        except Exception as exc:
            self._logger.error("Bağlantı testi başarısız: %s", exc)
            return False

    # ──────────────────────────────────────────
    # Dahili metodlar (değişmedi)
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
                    port=self._config.port,
                    connection_timeout=self._config.timeout,
                )

                with self._lock:
                    self._conn = conn
                    changed = not self._online
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
            conn = self._conn
            self._conn = None
            if self._online:
                self._online = False
                notify = True

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
