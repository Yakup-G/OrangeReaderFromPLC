"""
plc_reader.py  —  FINS/TCP ve FINS/UDP ile Omron PLC Okuyucu
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from config import PLCConfig, FinsTag

# İstemciyi import ediyoruz
from client import OmronFinsClient

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
        self._client:             Optional[OmronFinsClient] = None
        self._stop                = threading.Event()
        self._connection_listener = connection_listener
        self._online              = False

    def stop(self) -> None:
        self._stop.set()
        self._close()

    def read(self, tags: List[FinsTag]) -> Dict[str, object]:
        if not tags:
            return {}

        while not self._stop.is_set():
            client = self._ensure_connection()
            if client is None:
                break

            try:
                values: Dict[str, object] = {}

                for tag in tags:
                    try:
                        success, result, message = self._read_single_tag(client, tag)
                        if success:
                            scaled = round(float(result) * tag.scale, 4)
                            values[tag.label] = scaled
                            self._logger.debug("OK  %s[%s%s] = %s", 
                                             tag.label, tag.memory_area.upper(), tag.address, scaled)
                        else:
                            self._logger.warning("%s okunamadı: %s", tag.label, message)
                            values[tag.label] = None
                    except Exception as exc:
                        if self._is_conn_error(exc):
                            self._logger.warning("Bağlantı hatası, yeniden bağlanılıyor...")
                            self._reset()
                            break
                        else:
                            values[tag.label] = None

                else:
                    return values

            except Exception as exc:
                self._logger.exception("Okuma hatası: %s", exc)
                self._reset()

        raise RuntimeError("PLCReader durduruldu.")

    def _read_single_tag(self, client: OmronFinsClient, tag: FinsTag):
        """Tek tag okuma"""
        address_str = str(tag.address)
        return client.read_variable(
            memory_area=tag.memory_area,
            address_str=address_str,
            data_type=tag.data_type
        )

    def test_connection(self) -> bool:
        """Bağlantı testi"""
        client = OmronFinsClient()
        success, msg = client.connect(
            ip_address=self._config.ip,
            port=self._config.port,
            dest_node=self._config.fins_node,
            src_node=self._config.client_node,
            protocol=self._config.protocol
        )
        if success:
            client.disconnect()
        return success

    def _ensure_connection(self) -> Optional[OmronFinsClient]:
        with self._lock:
            if self._client and self._client.connected:
                return self._client

        while not self._stop.is_set():
            try:
                self._logger.info("PLC'ye bağlanılıyor... (%s)", self._config.protocol)
                
                client = OmronFinsClient()
                success, message = client.connect(
                    ip_address=self._config.ip,
                    port=self._config.port,
                    dest_node=self._config.fins_node,
                    src_node=self._config.client_node,
                    protocol=self._config.protocol
                )

                if success:
                    with self._lock:
                        self._client = client
                        if not self._online:
                            self._online = True
                            self._notify(True)
                    self._logger.info("✓ PLC bağlantısı kuruldu (%s)", self._config.protocol)
                    return client
                else:
                    self._logger.error("Bağlantı başarısız: %s", message)

            except Exception as exc:
                self._logger.error("Bağlantı hatası: %s", exc)

            self._stop.wait(self._reconnect_delay)

        return None

    def _reset(self) -> None:
        self._close()
        self._stop.wait(self._reconnect_delay)

    def _close(self) -> None:
        notify = False
        with self._lock:
            if self._online:
                self._online = False
                notify = True
            client = self._client
            self._client = None

        if client:
            try:
                client.disconnect()
            except:
                pass

        if notify:
            self._notify(False)

    def _is_conn_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(k in msg for k in ("timeout", "connection", "refused", "reset", "network"))

    def _notify(self, is_connected: bool) -> None:
        if self._connection_listener:
            try:
                self._connection_listener(is_connected, datetime.now(timezone.utc))
            except Exception:
                self._logger.exception("Listener hatası")
