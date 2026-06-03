"""
plc_reader.py  —  FINS Protokolü ile Omron PLC Okuyucu
────────────────────────────────────────────────────────────
Omron N-Serisi PLC'den FINS/TCP protokolü ile veri okur.
Tag ismi gerekmez — direkt D100, D200 gibi bellek adresleri kullanılır.

Kullanılan kütüphane: fins
    pip install fins

FINS Bellek Alanları:
    d = Data Memory  (D0..D32767)   ← En çok kullanılan
    c = CIO/IO       (C0..C6143)
    h = Holding Bit  (H0..H511)
    w = Work         (W0..W511)
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from fins import FinsConnection

from config import PLCConfig, FinsTag

LOGGER = logging.getLogger(__name__)


class PLCReader:
    """
    FINS/TCP üzerinden Omron PLC'den sürekli veri okur.
    Bağlantı kopunca otomatik yeniden bağlanır.
    Thread-safe tasarlanmıştır — arka planda güvenle çalışır.
    """

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
        self._connection:         Optional[FinsConnection] = None
        self._stop_event          = threading.Event()
        self._connection_listener = connection_listener
        self._connection_online   = False

    def stop(self) -> None:
        """Okuyucuyu durdur ve bağlantıyı kapat."""
        self._stop_event.set()
        self._close_connection()

    def read(self, tags: List[FinsTag]) -> Dict[str, object]:
        """
        Verilen FINS tag listesini PLC'den oku.

        Her tag için:
            conn.read(memory_area, address, data_type)
        çağrısı yapılır ve sonuç ham değer * scale olarak döndürülür.

        Döndürülen dict örneği:
            {
                "Çalışma Saati":   1240.0,
                "Çalışma Durumu":  1.0,
                "Arıza Kodu":      0.0,
                "Sıcaklık":        24.5,
                "Devir":           1450.0,
            }
        """
        if not tags:
            return {}

        while not self._stop_event.is_set():
            conn = self._ensure_connection()
            if conn is None:
                break

            try:
                values: Dict[str, object] = {}

                for tag in tags:
                    try:
                        # FINS okuma — örnek: conn.read("d", 100, "ui")
                        raw = conn.read(
                            memory_area     = tag.memory_area,
                            word_address    = tag.address,
                            data_type       = tag.data_type,
                            number_of_values= 1,
                        )

                        # fins kütüphanesi liste döndürür — ilk elemanı al
                        raw_value = raw[0] if isinstance(raw, (list, tuple)) else raw

                        # Sayısal değere çevir
                        if isinstance(raw_value, (bytes, bytearray)):
                            raw_value = int.from_bytes(raw_value, "big")
                        else:
                            raw_value = float(raw_value)

                        # Scale uygula
                        values[tag.label] = round(raw_value * tag.scale, 4)

                        self._logger.debug(
                            "Okundu: %s[%s%d] = %s %s",
                            tag.label,
                            tag.memory_area.upper(),
                            tag.address,
                            values[tag.label],
                            tag.unit,
                        )

                    except Exception as exc:
                        if self._is_connection_issue(exc):
                            self._logger.warning(
                                "%s[%s%d] okuma hatası: %s — Yeniden bağlanılıyor...",
                                tag.label, tag.memory_area.upper(), tag.address, exc,
                            )
                            self._reset_connection()
                            break   # İç döngüden çık, dışarıdaki while yeniden dener

                        self._logger.warning(
                            "%s[%s%d] okunamadı: %s — Atlanıyor.",
                            tag.label, tag.memory_area.upper(), tag.address, exc,
                        )
                        values[tag.label] = None
                        continue

                else:
                    # Tüm tag'ler başarıyla okundu
                    return values

            except Exception as exc:
                self._logger.exception("Beklenmedik PLC okuma hatası: %s", exc)
                self._reset_connection()

        raise RuntimeError("PLCReader durduruldu — okuma tamamlanamadı.")

    def test_connection(self) -> bool:
        """
        Bağlantıyı test et — kurulum sırasında kullanışlı.
        True = bağlantı başarılı, False = başarısız.
        """
        try:
            conn = FinsConnection(
                host        = self._config.ip,
                port        = self._config.port,
                destination_node_address = self._config.fins_node,
                source_node_address      = self._config.client_node,
            )
            # Basit bir okuma dene — D0 adresini oku
            conn.read("d", 0, "ui")
            conn.close()
            return True
        except Exception as exc:
            self._logger.error("Bağlantı testi başarısız: %s", exc)
            return False

    # ──────────────────────────────────────────
    # Dahili metodlar
    # ──────────────────────────────────────────

    def _ensure_connection(self) -> Optional[FinsConnection]:
        """Aktif bağlantıyı döndür, yoksa yeni bağlantı kur."""

        with self._lock:
            if self._connection is not None:
                return self._connection

        while not self._stop_event.is_set():
            try:
                self._logger.info(
                    "PLC'ye bağlanılıyor: %s:%s (FINS node=%s)",
                    self._config.ip, self._config.port, self._config.fins_node,
                )

                connection = FinsConnection(
                    host        = self._config.ip,
                    port        = self._config.port,
                    destination_node_address = self._config.fins_node,
                    source_node_address      = self._config.client_node,
                )

                with self._lock:
                    self._connection    = connection
                    state_changed       = not self._connection_online
                    self._connection_online = True

                if state_changed:
                    self._notify_connection_state(True)

                self._logger.info("✓ PLC bağlantısı kuruldu: %s", self._config.ip)
                return connection

            except Exception as exc:
                self._logger.error(
                    "PLC bağlantısı kurulamadı (%s): %s — %.1fs sonra tekrar denenecek.",
                    self._config.ip, exc, self._reconnect_delay,
                )
                self._stop_event.wait(self._reconnect_delay)

        return None

    def _reset_connection(self) -> None:
        """Bağlantıyı sıfırla — bir sonraki okumada yeniden bağlanılır."""
        self._close_connection()
        self._stop_event.wait(self._reconnect_delay)

    def _close_connection(self) -> None:
        """Bağlantıyı kapat."""
        notify = False
        with self._lock:
            connection = self._connection
            self._connection = None
            if self._connection_online:
                self._connection_online = False
                notify = True

        if connection is not None:
            try:
                connection.close()
                self._logger.info("PLC bağlantısı kapatıldı: %s", self._config.ip)
            except Exception:
                self._logger.debug("Bağlantı kapatılamadı (sorun değil)", exc_info=True)

        if notify:
            self._notify_connection_state(False)

    def _is_connection_issue(self, exc: Exception) -> bool:
        """Bu hata bağlantı sorunu mu?"""
        if isinstance(exc, (ConnectionError, TimeoutError, OSError, BrokenPipeError)):
            return True
        msg = str(exc).lower()
        return any(k in msg for k in ("timeout", "connection", "network", "refused", "reset", "fins"))

    def _notify_connection_state(self, is_connected: bool) -> None:
        listener = self._connection_listener
        if listener is None:
            return
        try:
            listener(is_connected, datetime.now(timezone.utc))
        except Exception:
            self._logger.exception("Bağlantı listener hatası")
