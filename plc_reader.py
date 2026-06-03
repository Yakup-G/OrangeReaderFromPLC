"""
plc_reader.py  —  FINS/TCP ve FINS/UDP ile Omron PLC Okuyucu
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from config import PLCConfig, FinsTag

# client.py aynı klasörde olduğu için direkt import
import client
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
            client_obj = self._ensure_connection()
            if client_obj is None:
                break

            try:
                values: Dict[str, object] = {}

                for tag in tags:
                    try:
                        success, result, message = self._read_single_tag(client_obj, tag)
                        if success:
                            scaled = round(float(result) * tag.scale, 4)
                            values[tag.label] = scaled
                            self._logger.debug(
                                "OK  %s[%s%s] = %s %s", 
                                tag.label, tag.memory_area.upper(), tag.address, scaled, tag.unit
                            )
                        else:
                            self._logger.warning("%s okunamadı: %s", tag.label, message)
                            values[tag.label] = None

                    except Exception as exc:
                        if self._is_conn_error(exc):
                            self._logger.warning("Bağlantı hatası — yeniden bağlanılıyor...")
                            self._reset()
                            break
                        else:
                            values[tag.label] = None

                else:
                    return values

            except Exception as exc:
                self._logger.exception("Beklenmedik okuma hatası")
                self._reset()

        raise RuntimeError("PLCReader durduruldu.")

    def _read_single_tag(self, client_obj: OmronFinsClient, tag: FinsTag):
        address_str = str(tag.address)
        return client_obj.read_variable(
            memory_area=tag.memory_area,
            address_str=address_str,
            data_type=tag.data_type
        )

    def test_connection(self) -> bool:
        """Bağlantı testi"""
        try:
            test_client = OmronFinsClient()
            success, msg = test_client.connect(
                ip_address=self._config.ip,
                port=self._config.port,
                dest_node=self._config.fins_node,
                src_node=self._config.client_node,
                protocol=self._config.protocol
            )
            if success:
                test_client.disconnect()
                return True
            else:
                self._logger.error("Test bağlantısı başarısız: %s", msg)
                return False
        except Exception as e:
            self._logger.error("Test sırasında hata: %s", e)
            return False

    def _ensure_connection(self) -> Optional[OmronFinsClient]:
        with self._lock:
            if self._client and getattr(self._client, 'connected', False):
                return self._client

        while not self._stop.is_set():
            try:
                self._logger.info("PLC'ye bağlanılıyor... (%s)", self._config.protocol)
                
                new_client = OmronFinsClient()
                success, message = new_client.connect(
                    ip_address=self._config.ip,
                    port=self._config.port,
                    dest_node=self._config.fins_node,
                    src_node=self._config.client_node,
                    protocol=self._config.protocol
                )

                if success:
                    with self._lock:
                        self._client = new_client
                        if not self._online:
                            self._online = True
                            self._notify(True)
                    self._logger.info("✓ PLC bağlantısı kuruldu (%s)", self._config.protocol)
                    return new_client
                else:
                    self._logger.error("Bağlantı başarısız: %s", message)

            except Exception as exc:
                self._logger.error("Bağlantı hatası: %s", exc)

            self._stop.wait(self._reconnect_delay)

        return None

    # Diğer metodlar (_reset, _close, _is_conn_error, _notify) aynı kalıyor...
    def _reset(self) -> None:
        self._close()
        self._stop.wait(self._reconnect_delay)

    def _close(self) -> None:
        notify = False
        with self._lock:
            if self._online:
                self._online = False
                notify = True
            client_obj = self._client
            self._client = None

        if client_obj:
            try:
                client_obj.disconnect()
            except:
                pass

        if notify:
            self._notify(False)

    def _is_conn_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(k in msg for k in ("timeout", "connection", "refused", "reset", "network", "broken"))

    def _notify(self, is_connected: bool) -> None:
        if self._connection_listener:
            try:
                self._connection_listener(is_connected, datetime.now(timezone.utc))
            except Exception:
                self._logger.exception("Listener hatası")
