"""PLC reader utilities built on top of the :mod:`aphyt` library."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, Optional

from aphyt import omron

from .config import PLCConfig, TagDefinition

LOGGER = logging.getLogger(__name__)


class PLCReader:
    """Continuously reads PLC tags while handling connection resilience."""

    def __init__(
        self,
        config: PLCConfig,
        reconnect_delay: float = 5.0,
        logger: Optional[logging.Logger] = None,
        connection_listener: Optional[Callable[[bool, datetime], None]] = None,
    ) -> None:
        self._config = config
        self._reconnect_delay = max(0.5, reconnect_delay)
        self._logger = logger or LOGGER
        self._lock = threading.Lock()
        self._connection: Optional[omron.NSeries] = None
        self._stop_event = threading.Event()
        self._connection_listener = connection_listener
        self._connection_online = False

    def stop(self) -> None:
        """Signal the reader to stop and close any open connection."""

        self._stop_event.set()
        self._close_connection()

    def read(self, tags: Iterable[TagDefinition]) -> Dict[str, object]:
        """Read the provided tag collection from the PLC.

        This method blocks until the read completes. Should the connection drop or
        a read fail, the method will transparently attempt to reconnect and retry
        until successful or until :meth:`stop` is invoked.
        """

        tag_list = list(tags)
        if not tag_list:
            return {}

        while not self._stop_event.is_set():
            conn = self._ensure_connection()
            if conn is None:
                break

            try:
                values: Dict[str, object] = {}
                for tag in tag_list:
                    try:
                        values[tag.name] = conn.read_variable(tag.name)
                    except Exception as exc:  # pragma: no cover - depends on hardware
                        if self._is_connection_issue(exc):
                            self._logger.warning(
                                "Failed to read tag '%s': %s. Reconnecting...",
                                tag.name,
                                exc,
                            )
                            self._reset_connection()
                            break

                        self._logger.warning(
                            "Tag '%s' could not be read: %s. Skipping.",
                            tag.name,
                            exc,
                        )
                        continue
                else:
                    return values
            except Exception as exc:  # pragma: no cover - defensive logging
                self._logger.exception("Unexpected PLC read failure: %s", exc)
                self._reset_connection()

        raise RuntimeError("PLCReader stopped before completing read cycle.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connection(self) -> Optional[omron.NSeries]:
        """Return an active connection, establishing one if required."""

        with self._lock:
            if self._connection is not None:
                return self._connection

        while not self._stop_event.is_set():
            try:
                connection = omron.NSeries(self._config.ip, timeout=self._config.timeout)
                self._logger.info(
                    "Connected to PLC %s:%s", self._config.ip, self._config.port
                )
                with self._lock:
                    self._connection = connection
                    state_changed = not self._connection_online
                    self._connection_online = True
                if state_changed:
                    self._notify_connection_state(True)
                return connection
            except Exception as exc:  # pragma: no cover - depends on network
                self._logger.error(
                    "PLC connection to %s failed: %s. Retrying in %.1fs...",
                    self._config.ip,
                    exc,
                    self._reconnect_delay,
                )
                time.sleep(self._reconnect_delay)

        return None

    def _reset_connection(self) -> None:
        """Drop the current PLC connection to trigger a reconnect."""

        self._close_connection()
        time.sleep(self._reconnect_delay)

    def _close_connection(self) -> None:
        """Close and dispose of the current PLC connection."""

        notify = False
        with self._lock:
            connection = self._connection
            self._connection = None
            if self._connection_online:
                self._connection_online = False
                notify = True

        if connection is not None:
            try:
                connection.close_explicit()
                self._logger.info("Closed PLC connection to %s", self._config.ip)
            except Exception:  # pragma: no cover - best-effort cleanup
                self._logger.debug("Failed to close PLC connection cleanly", exc_info=True)

        if notify:
            self._notify_connection_state(False)

    def _is_connection_issue(self, exc: Exception) -> bool:
        """Return whether an exception likely indicates a connection problem."""

        connection_errors = (ConnectionError, TimeoutError, OSError)
        if isinstance(exc, connection_errors):
            return True

        message = str(exc).lower()
        return any(keyword in message for keyword in ("timeout", "connection", "network"))

    def _notify_connection_state(self, is_connected: bool) -> None:
        listener = self._connection_listener
        if listener is None:
            return

        try:
            listener(is_connected, datetime.now(timezone.utc))
        except Exception:  # pragma: no cover - listener failures should not crash the loop
            self._logger.exception("Connection listener raised an exception")

