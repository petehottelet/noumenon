"""Offline, standalone guards for the Noumenon test suite."""

import ipaddress
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BLOCKED_PACKAGES = frozenset({"smythe", "benchmarks", "screensaver"})


def _importer() -> str:
    """The module name that asked for an import, past the import machinery and pytest."""
    frame = sys._getframe(2)
    while frame is not None and ("importlib" in frame.f_code.co_filename
                                 or frame.f_code.co_filename.startswith("<frozen")
                                 or frame.f_globals.get("__name__", "").startswith("_pytest")):
        frame = frame.f_back
    return frame.f_globals.get("__name__", "") if frame is not None else ""


class _BlockSmythePackages:
    """Fail loudly if code under test imports Smythe's Python packages.

    Noumenon vendors the catalog and motion data it needs. An environment that
    also has Smythe installed must not satisfy these imports silently. The one
    exception is the optional live glyph generator in ``live/``, which runs on
    Smythe by design; only its modules, their tests and Smythe itself may import it.
    """

    def find_spec(self, name, path=None, target=None):
        if name.partition(".")[0] in BLOCKED_PACKAGES:
            importer = _importer()
            if name.partition(".")[0] == "smythe" and (importer.partition(".")[0] in {"live", "smythe"}
                                                       or importer.startswith("test_live")):
                return None
            raise ImportError(f"Noumenon must not import {name!r}")
        return None


sys.meta_path.insert(0, _BlockSmythePackages())


def _offline_network(event, args):
    """Reject external Python socket traffic, including during test collection.

    This is a test guardrail, not an OS sandbox: separately launched processes
    need their own offline fixtures.
    """
    if event == "socket.getaddrinfo":
        host = args[0]
    elif event in {"socket.connect", "socket.sendto"}:
        sock, address = args
        if sock.family not in {socket.AF_INET, socket.AF_INET6}:
            return
        host = address[0]
    else:
        return
    if isinstance(host, bytes):
        host = host.decode("ascii")
    if host in {None, "localhost"}:
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise RuntimeError("Offline test suite blocked external network dispatch")


sys.addaudithook(_offline_network)
