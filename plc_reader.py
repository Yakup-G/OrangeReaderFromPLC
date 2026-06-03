"""
plc_reader.py  —  FINS/TCP ve FINS/UDP ile Omron PLC Okuyucu
"""

from __future__ import annotations

import logging
import threading
import sys
import os
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple, Any

from fins.tcp import TCPFinsConnection
from fins.udp import UDPFinsConnection
import fins.fins_common

from config import PLCConfig, FinsTag

LOGGER = logging.getLogger(__name__)


class OmronFinsClient:
    """client.py'deki mantık buraya taşındı"""
    def __init__(self):
        self.client: Optional[Any] = None
        self.ip_address = ""
        self.port = 9600
        self.connected = False
        self.protocol = "UDP"

    def connect(self, ip_address: str, port: int = 9600, dest_node: int = 0, 
                src_node: int = 0, protocol: str = "UDP") -> Tuple[bool, str]:
        try:
            self.protocol = protocol.upper()
            
            if self.protocol == "TCP":
                self.client = TCPFinsConnection()
                self.client.connect(ip_address, port=port, connection_timeout=3.0)
            else:
                self.client = UDPFinsConnection()
                self.client.connect(ip_address, port=port)

            if hasattr(self.client, 'fins_socket'):
                self.client.fins_socket.settimeout(3.0)

            if dest_node != 0:
                self.client.dest_node_add = dest_node
            if src_node != 0:
                self.client.srce_node_add = src_node

            if self.protocol == "UDP":
                self.client.cpu_unit_status_read()  # UDP için doğrulama

            self.ip_address = ip_address
            self.port = port
            self.connected = True
            LOGGER.info(f"Connected to {ip_address}:{port} over {protocol}")
            return True, "Connected successfully"
        except Exception as e:
            self.connected = False
            error_msg = f"Connection failed: {str(e)}"
            LOGGER.error(error_msg)
            return False, error_msg

    def disconnect(self):
        if self.client:
            try:
                if hasattr(self.client, 'fins_socket') and self.client.fins_socket:
                    self.client.fins_socket.close()
            except:
                pass
            self.client = None
        self.connected = False

    def read_variable(self, memory_area: str, address_str: str, data_type: str = 'w') -> Tuple[bool, Any, str]:
        if not self.connected or not self.client:
            return False, None, "Not connected"
        try:
            # Bit okuması (Bool)
            if data_type.lower() == 'b':
                return self._read_bit(memory_area, address_str)

            # Normal okuma
            result = self.client.read(
                memory_area=memory_area.lower(),
                word_address=int(address_str),
                data_type=data_type.lower(),
                number_of_values=1
            )
            raw_val = result[0] if isinstance(result, (list, tuple)) else result
            if isinstance(raw_val, (bytes, bytearray)):
                raw_val = int.from_bytes(raw_val, "big")
            return True, raw_val, "success"

        except Exception as e:
            return False, None, str(e)

    def _read_bit(self, memory_area: str, address_str: str) -> Tuple[bool, Any, str]:
        try:
            if "." in address_str:
                word, bit = map(int, address_str.split("."))
            else:
                word, bit = int(address_str), 0

            memory_areas = fins.fins_common.FinsPLCMemoryAreas()
            ma = memory_area.lower()
            if ma == 'w': read_area = memory_areas.WORK_BIT
            elif ma == 'c': read_area = memory_areas.CIO_BIT
            elif ma == 'd': read_area = memory_areas.DATA_MEMORY_BIT
            elif ma == 'h': read_area = memory_areas.HOLDING_BIT
            else: read_area = memory_areas.DATA_MEMORY_BIT

            begin_address = word.to_bytes(2, 'big') + bit.to_bytes(1, 'big')
            response = self.client.memory_area_read(read_area, begin_address, 1)

            fins_response = fins.fins_common.FinsResponseFrame()
            fins_response.from_bytes(response)

            if not fins_response.end_code.startswith(b'\x00'):
                return False, None, f"End Code: {fins_response.end_code}"

            return True, int.from_bytes(fins_response.text, 'big'), "success"

        except Exception as e:
            return False, None, str(e)


# ─────────────────────────────────────────────
# PLCReader Sınıfı
# ─────────────────────────────────────────────

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
                        success, result, msg = client.read_variable(
                            memory_area=tag.memory_area,
                            address_str=str(tag.address),
                            data_type=tag.data_type
                        )
                        if success:
                            scaled = round(float(result) * tag.scale, 4)
                            values[tag.label] = scaled
                            self._logger.debug("OK  %s = %s", tag.label, scaled)
                        else:
                            self._logger.warning("%s okunamadı: %s", tag.label, msg)
                            values[tag.label] = None
                    except Exception as exc:
                        if self._is_conn_error(exc):
                            self._reset()
                            break
                        values[tag.label] = None
                else:
                    return values
            except Exception as exc:
                self._logger.exception("Okuma hatası")
                self._reset()

        raise RuntimeError("PLCReader durduruldu.")

    def test_connection(self) -> bool:
        test_client = OmronFinsClient()
        success, _ = test_client.connect(
            ip_address=self._config.ip,
            port=self._config.port,
            dest_node=self._config.fins_node,
            src_node=self._config.client_node,
            protocol=self._config.protocol
        )
        if success:
            test_client.disconnect()
        return success

    def _ensure_connection(self) -> Optional[OmronFinsClient]:
        with self._lock:
            if self._client and self._client.connected:
                return self._client

        while not self._stop.is_set():
            try:
                self._logger.info("PLC'ye bağlanılıyor... (%s)", self._config.protocol)
                new_client = OmronFinsClient()
                success, msg = new_client.connect(
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
                    self._logger.info("✓ Bağlantı kuruldu (%s)", self._config.protocol)
                    return new_client
            except Exception as exc:
                self._logger.error("Bağlantı hatası: %s", exc)

            self._stop.wait(self._reconnect_delay)
        return None

    def _reset(self):
        self._close()
        self._stop.wait(self._reconnect_delay)

    def _close(self):
        notify = False
        with self._lock:
            if self._online:
                self._online = False
                notify = True
            client = self._client
            self._client = None

        if client:
            client.disconnect()
        if notify:
            self._notify(False)

    def _is_conn_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(k in msg for k in ("timeout", "connection", "refused", "reset", "network"))

    def _notify(self, is_connected: bool):
        if self._connection_listener:
            try:
                self._connection_listener(is_connected, datetime.now(timezone.utc))
            except:
                pass
