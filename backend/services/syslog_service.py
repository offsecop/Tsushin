"""
Syslog Service — RFC 5424 Formatter, Transport, Circuit Breaker
Provides syslog streaming for tenant audit events via TCP, UDP, or TLS.
Uses Python stdlib only (socket, ssl) — no external dependencies.
"""

import json
import logging
import os
import socket
import ssl
import threading
import time
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Tsushin Private Enterprise Number placeholder (register with IANA for production)
TSUSHIN_PEN = "49876"


class RFC5424Formatter:
    """Format audit event dicts into RFC 5424 structured syslog messages."""

    SEVERITY_MAP = {
        "info": 6,       # Informational
        "warning": 4,    # Warning
        "critical": 2,   # Critical
    }

    FACILITY_NAMES = {
        0: "kern", 1: "user", 2: "mail", 3: "daemon", 4: "auth",
        10: "authpriv", 13: "audit", 16: "local0", 17: "local1",
        18: "local2", 19: "local3", 20: "local4", 21: "local5",
        22: "local6", 23: "local7",
    }

    @classmethod
    def format_from_dict(
        cls,
        event: dict,
        facility: int = 1,
        app_name: str = "tsushin",
        hostname: Optional[str] = None,
    ) -> str:
        """
        Build RFC 5424 syslog message from event dict.

        Format: <priority>version timestamp hostname app-name procid msgid [SD-ELEMENT] msg
        """
        sev_name = event.get("severity", "info")
        severity = cls.SEVERITY_MAP.get(sev_name, 6)
        priority = facility * 8 + severity

        ts = event.get("created_at") or datetime.utcnow().isoformat()
        if not ts.endswith("Z") and "+" not in ts:
            ts += "Z"

        host = hostname or socket.getfqdn()
        procid = str(os.getpid())
        msgid = "-"

        # Structured data element [tsushin@PEN key=value ...]
        sd_params = []
        for key in ("tenant_id", "action", "severity", "user_id", "resource_type",
                     "resource_id", "channel", "ip_address"):
            val = event.get(key)
            if val is not None:
                # RFC 5424 SD-PARAM: escape \, ", ]
                safe_val = str(val).replace("\\", "\\\\").replace('"', '\\"').replace("]", "\\]")
                sd_params.append(f'{key}="{safe_val}"')

        sd = f"[tsushin@{TSUSHIN_PEN} {' '.join(sd_params)}]" if sd_params else "-"

        # Human-readable message
        action = event.get("action", "unknown")
        details = event.get("details")
        msg = action
        if details:
            try:
                detail_str = json.dumps(details) if isinstance(details, dict) else str(details)
                msg = f"{action} {detail_str}"
            except Exception:
                pass

        return f"<{priority}>1 {ts} {host} {app_name} {procid} {msgid} {sd} {msg}"


class CircuitBreaker:
    """
    Per-tenant circuit breaker.
    CLOSED -> OPEN after FAILURE_THRESHOLD consecutive failures.
    OPEN -> HALF_OPEN after RECOVERY_TIMEOUT_S.
    HALF_OPEN -> CLOSED on success, OPEN on failure.
    """

    FAILURE_THRESHOLD = 5
    RECOVERY_TIMEOUT_S = 60

    def __init__(self):
        self._states: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def can_send(self, tenant_id: str) -> bool:
        with self._lock:
            state = self._states.get(tenant_id)
            if not state or state["state"] == "closed":
                return True
            if state["state"] == "open":
                elapsed = time.time() - state["last_failure_time"]
                if elapsed >= self.RECOVERY_TIMEOUT_S:
                    state["state"] = "half_open"
                    return True
                return False
            # half_open: allow one probe
            return True

    def record_success(self, tenant_id: str):
        with self._lock:
            self._states[tenant_id] = {"state": "closed", "failures": 0, "last_failure_time": 0}

    def record_failure(self, tenant_id: str):
        with self._lock:
            state = self._states.get(tenant_id, {"state": "closed", "failures": 0, "last_failure_time": 0})
            state["failures"] = state.get("failures", 0) + 1
            state["last_failure_time"] = time.time()
            if state["failures"] >= self.FAILURE_THRESHOLD:
                state["state"] = "open"
            self._states[tenant_id] = state


class SyslogConnectionPool:
    """
    Per-tenant persistent TCP/TLS socket pool.
    UDP is connectionless — no pooling needed.
    """

    def __init__(self):
        self._connections: Dict[str, socket.socket] = {}
        self._lock = threading.Lock()

    def get_connection(
        self,
        tenant_id: str,
        host: str,
        port: int,
        protocol: str,
        tls_config: Optional[dict] = None,
    ) -> socket.socket:
        """Get or create a connection for a tenant."""
        with self._lock:
            existing = self._connections.get(tenant_id)
            if existing:
                try:
                    # Quick liveness check
                    existing.getpeername()
                    return existing
                except (OSError, socket.error):
                    self._close_socket(existing)
                    del self._connections[tenant_id]

            sock = self._create_connection(host, port, protocol, tls_config)
            if protocol != "udp":
                self._connections[tenant_id] = sock
            return sock

    def _create_connection(
        self, host: str, port: int, protocol: str, tls_config: Optional[dict] = None
    ) -> socket.socket:
        if protocol == "udp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            return sock

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((host, port))

        if protocol == "tls" and tls_config:
            ctx = ssl.create_default_context()
            if not tls_config.get("verify", True):
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

            ca_cert = tls_config.get("ca_cert")
            if ca_cert:
                ctx.load_verify_locations(cadata=ca_cert)

            client_cert = tls_config.get("client_cert")
            client_key = tls_config.get("client_key")
            if client_cert and client_key:
                import tempfile
                with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as cf:
                    cf.write(client_cert)
                    cert_path = cf.name
                with tempfile.NamedTemporaryFile(mode="w", suffix=".key", delete=False) as kf:
                    kf.write(client_key)
                    key_path = kf.name
                try:
                    ctx.load_cert_chain(cert_path, key_path)
                finally:
                    os.unlink(cert_path)
                    os.unlink(key_path)

            sock = ctx.wrap_socket(sock, server_hostname=host)

        return sock

    def close_connection(self, tenant_id: str):
        with self._lock:
            sock = self._connections.pop(tenant_id, None)
            if sock:
                self._close_socket(sock)

    def close_all(self):
        with self._lock:
            for sock in self._connections.values():
                self._close_socket(sock)
            self._connections.clear()

    @staticmethod
    def _close_socket(sock: socket.socket):
        try:
            sock.close()
        except Exception:
            pass


class SyslogSender:
    """Sends formatted syslog messages via TCP, UDP, or TLS."""

    def __init__(self):
        self._pool = SyslogConnectionPool()
        self._breaker = CircuitBreaker()

    def send(
        self,
        tenant_id: str,
        message: str,
        host: str,
        port: int,
        protocol: str,
        tls_config: Optional[dict] = None,
    ) -> bool:
        """Send a syslog message. Returns True on success."""
        if not self._breaker.can_send(tenant_id):
            return False

        try:
            sock = self._pool.get_connection(tenant_id, host, port, protocol, tls_config)
            data = message.encode("utf-8")

            if protocol == "udp":
                sock.sendto(data, (host, port))
            else:
                # TCP/TLS: send with octet-counted framing (RFC 5425)
                framed = f"{len(data)} ".encode("utf-8") + data
                sock.sendall(framed)

            self._breaker.record_success(tenant_id)
            return True

        except Exception as e:
            logger.warning(f"[Syslog] Send failed for tenant {tenant_id}: {e}")
            self._breaker.record_failure(tenant_id)
            self._pool.close_connection(tenant_id)
            return False

    def test_connection(
        self,
        host: str,
        port: int,
        protocol: str,
        tls_config: Optional[dict] = None,
    ) -> dict:
        """Test connectivity to a syslog server."""
        start = time.time()
        try:
            pool = SyslogConnectionPool()
            sock = pool._create_connection(host, port, protocol, tls_config)

            # Send a test message
            test_msg = RFC5424Formatter.format_from_dict(
                {"action": "syslog.test", "severity": "info", "tenant_id": "test"},
                app_name="tsushin",
            )
            data = test_msg.encode("utf-8")

            if protocol == "udp":
                sock.sendto(data, (host, port))
            else:
                framed = f"{len(data)} ".encode("utf-8") + data
                sock.sendall(framed)

            pool._close_socket(sock)
            latency = (time.time() - start) * 1000

            return {"success": True, "message": f"Connected to {host}:{port} via {protocol.upper()}", "latency_ms": round(latency, 1)}

        except socket.timeout:
            return {"success": False, "message": f"Connection timed out ({host}:{port})", "latency_ms": None}
        except ConnectionRefusedError:
            return {"success": False, "message": f"Connection refused ({host}:{port})", "latency_ms": None}
        except ssl.SSLError as e:
            return {"success": False, "message": f"TLS error: {e}", "latency_ms": None}
        except Exception as e:
            return {"success": False, "message": str(e), "latency_ms": None}

    def close_all(self):
        self._pool.close_all()
