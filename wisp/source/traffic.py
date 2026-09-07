"""UDP traffic generator — the other half of a one-board sensor.

A single ESP32 measures CSI on frames it RECEIVES, so with one board the sampling rate is
not ours by default: it is whatever the router happens to send us. That is the single
biggest difference from the two-board rig, where our own transmitter set the rate.

The fix is embarrassingly simple. The firmware binds a UDP port and discards everything
that arrives; this module sends datagrams at a chosen rate. The payload is irrelevant —
each datagram is one received Wi-Fi frame, and every received frame is one CSI sample. So
``--hz 50`` really does mean 50 samples per second, evenly spaced, from a transmitter
(the router, or the laptop in SoftAP mode) that never moves.

It lives next to the sources because it is part of the measurement, not a utility: without
it the "sample rate" in the config is a wish. ``server/app.py`` starts one automatically
once the board reports its IP.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Optional


class UdpTrafficGenerator:
    """Sends fixed-size UDP datagrams to the board at a steady rate, in a background thread.

    Parameters
    ----------
    host : str
        The board's IP — printed by the firmware as ``CSI_INFO,...,ip=...`` (and
        auto-discovered from that line by the server).
    port : int
        Must match ``CONFIG_WISP_UDP_PORT`` in the firmware (8888 by default).
    hz : float
        Datagrams per second: the CSI sample rate you are asking for. What you actually get
        is ``achieved_hz`` — the network, the board's UART, or the OS timer can all cap it,
        and pretending otherwise would corrupt every window the pipeline sizes.
    payload_bytes : int
        Datagram size. Small is right: this is a clock, not a load test.
    """

    def __init__(self, host: str, port: int = 8888, hz: float = 50.0,
                 payload_bytes: int = 32) -> None:
        self.host = host
        self.port = int(port)
        self.hz = float(hz)
        self.payload = b"w" * max(1, int(payload_bytes))
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.sent = 0
        self.errors = 0
        self.started_at = 0.0
        self.last_error: Optional[str] = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> "UdpTrafficGenerator":
        if self._thread is not None:
            return self
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.started_at = time.time()
        self._thread = threading.Thread(target=self._run, name="wisp-traffic", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def __enter__(self) -> "UdpTrafficGenerator":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- the loop ----------------------------------------------------------
    def _run(self) -> None:
        interval = 1.0 / self.hz if self.hz > 0 else 0.02
        # Absolute deadlines, not sleep(interval): sleeping a fixed amount accumulates every
        # scheduling overshoot, so the real rate drifts below the requested one over minutes.
        next_at = time.perf_counter()
        addr = (self.host, self.port)
        while not self._stop.is_set():
            try:
                self._sock.sendto(self.payload, addr)   # type: ignore[union-attr]
                self.sent += 1
            except OSError as exc:
                # The board rebooting or the Wi-Fi dropping is normal; keep the clock running
                # so packets resume the moment it comes back.
                self.errors += 1
                self.last_error = str(exc)
                time.sleep(0.2)
            next_at += interval
            gap = next_at - time.perf_counter()
            if gap > 0:
                time.sleep(gap)
            else:
                next_at = time.perf_counter()   # fell behind: resync rather than spiral

    # -- reporting ---------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def achieved_hz(self) -> float:
        """Datagrams per second actually sent. Compare with ``hz``: a large shortfall means
        the OS timer or the network is the limit, and the real CSI rate follows this, not
        the requested one."""
        elapsed = time.time() - self.started_at
        return self.sent / elapsed if elapsed > 0.5 else 0.0

    def summary(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "requested_hz": round(self.hz, 1),
            "achieved_hz": round(self.achieved_hz, 1),
            "sent": self.sent,
            "errors": self.errors,
            "running": self.running,
        }
