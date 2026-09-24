"""mitmproxy addon for watching a mobile game's API traffic.

The console stays compact and readable; the full transcript (headers plus
bodies, with binary bodies base64-encoded) is appended as JSON Lines so it can
be re-read or diffed later.

Options, passed on the command line with --set:

    game_capture_dir=<path>   directory for the .jsonl transcript
    game_focus=<a,b,c>        show only hosts containing one of these substrings
    game_noise=<a,b,c>        hide hosts containing one of these substrings
    game_preview=<int>        max characters of a body echoed to the console

Filtering affects the console only. The .jsonl transcript always gets
everything, so a host you filtered out by mistake is never actually lost.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
from datetime import datetime

from mitmproxy import http

# Hosts that every Android device chatters with regardless of the game. Hidden
# from the console by default so the game's own calls stand out.
DEFAULT_NOISE = ",".join(
    [
        "google.com",
        "googleapis.com",
        "gstatic.com",
        "googleusercontent.com",
        "android.com",
        "doubleclick.net",
        "googlesyndication.com",
        "google-analytics.com",
        "crashlytics.com",
        "app-measurement.com",
        "gvt1.com",
        "gvt2.com",
        "ntp.org",
        "msftconnecttest.com",
    ]
)

MAX_PROTOBUF_DEPTH = 3


def _read_varint(buf: bytes, i: int):
    """Read a protobuf varint at offset i. Returns (value, next_offset)."""
    result = 0
    shift = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7
        if shift > 63:
            break
    return None, i


def guess_protobuf(buf: bytes, depth: int = 0):
    """Best-effort decode of protobuf wire format.

    Returns None the moment anything fails to parse, which is what makes this
    safe to try on arbitrary bytes: a successful parse that consumes the whole
    buffer is decent evidence the payload really is protobuf.
    """
    fields = []
    i = 0
    n = len(buf)
    while i < n:
        key, i = _read_varint(buf, i)
        if key is None:
            return None
        field_no = key >> 3
        wire = key & 7
        if field_no == 0:
            return None
        if wire == 0:
            value, i = _read_varint(buf, i)
            if value is None:
                return None
            fields.append({"field": field_no, "type": "varint", "value": value})
        elif wire == 1:
            if i + 8 > n:
                return None
            fields.append({"field": field_no, "type": "fixed64", "hex": buf[i : i + 8].hex()})
            i += 8
        elif wire == 5:
            if i + 4 > n:
                return None
            fields.append({"field": field_no, "type": "fixed32", "hex": buf[i : i + 4].hex()})
            i += 4
        elif wire == 2:
            length, i = _read_varint(buf, i)
            if length is None or i + length > n:
                return None
            chunk = buf[i : i + length]
            i += length
            entry = {"field": field_no, "type": "bytes", "length": length}
            nested = None
            if chunk and depth < MAX_PROTOBUF_DEPTH:
                nested = guess_protobuf(chunk, depth + 1)
            if nested:
                entry["message"] = nested
            else:
                text = _as_printable(chunk)
                if text is None:
                    entry["hex"] = chunk[:64].hex()
                else:
                    entry["string"] = text
            fields.append(entry)
        else:
            return None
    return fields or None


def _as_printable(raw: bytes):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(ord(c) < 32 and c not in "\t\n\r" for c in text):
        return None
    return text


def _human_size(n: int) -> str:
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%.1f MB" % (n / (1024.0 * 1024.0))


def describe_body(raw: bytes, headers) -> dict:
    """Turn a body into a JSON-serialisable description of itself."""
    if not raw:
        return {"kind": "empty", "size": 0}

    content_type = ""
    try:
        content_type = headers.get("content-type", "") or ""
    except Exception:
        pass

    text = None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    if text is not None:
        stripped = text.strip()
        if stripped[:1] in ("{", "["):
            try:
                return {
                    "kind": "json",
                    "size": len(raw),
                    "content_type": content_type,
                    "json": json.loads(stripped),
                }
            except ValueError:
                pass
        return {"kind": "text", "size": len(raw), "content_type": content_type, "text": text}

    described = {
        "kind": "binary",
        "size": len(raw),
        "content_type": content_type,
        "base64": base64.b64encode(raw).decode("ascii"),
        "hex_head": raw[:64].hex(),
    }
    fields = guess_protobuf(raw)
    if fields:
        described["protobuf_guess"] = fields
    return described


def preview_body(described: dict, limit: int) -> str:
    """One-or-few-line rendering of a body description for the console."""
    kind = described.get("kind")
    if kind == "empty":
        return ""
    if kind == "json":
        try:
            rendered = json.dumps(described["json"], ensure_ascii=False, sort_keys=False)
        except (TypeError, ValueError):
            rendered = str(described["json"])
    elif kind == "text":
        rendered = described["text"]
    else:
        if "protobuf_guess" in described:
            rendered = "protobuf? " + json.dumps(described["protobuf_guess"], ensure_ascii=False)
        else:
            rendered = "<binary> " + described.get("hex_head", "")
    rendered = " ".join(rendered.split())
    if len(rendered) > limit:
        rendered = rendered[:limit] + " ...(truncated, full body in the .jsonl)"
    return rendered


class GameApiLogger:
    def __init__(self):
        self._lock = threading.Lock()
        self._handle = None
        self._path = None
        self._seq = 0
        self._tls_failures = {}

    # -- lifecycle ---------------------------------------------------------

    def load(self, loader):
        loader.add_option(
            "game_capture_dir", str, "captures",
            "Directory for the JSON Lines transcript.",
        )
        loader.add_option(
            "game_focus", str, "",
            "Comma-separated host substrings; if set, only these reach the console.",
        )
        loader.add_option(
            "game_noise", str, DEFAULT_NOISE,
            "Comma-separated host substrings hidden from the console.",
        )
        loader.add_option(
            "game_preview", int, 1200,
            "Max characters of a body echoed to the console.",
        )

    def running(self):
        from mitmproxy import ctx

        directory = ctx.options.game_capture_dir or "captures"
        os.makedirs(directory, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        # The pid keeps several mitmproxy instances (one per redirected target)
        # from appending into the same file.
        self._path = os.path.join(directory, "api-%s-%d.jsonl" % (stamp, os.getpid()))
        self._handle = open(self._path, "a", encoding="utf-8")
        logging.info("game_api_logger: writing transcript to %s" % self._path)

    def done(self):
        if self._tls_failures:
            lines = ["", "TLS handshakes that failed (these hosts likely pin their certificate):"]
            for host, count in sorted(self._tls_failures.items(), key=lambda kv: -kv[1]):
                lines.append("    %-50s %d time(s)" % (host, count))
            lines.append("")
            logging.warning("\n".join(lines))
        with self._lock:
            if self._handle:
                self._handle.close()
                self._handle = None

    # -- helpers -----------------------------------------------------------

    def _write(self, record: dict):
        with self._lock:
            if not self._handle:
                return
            self._handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self._handle.flush()

    def _console_allows(self, host: str) -> bool:
        from mitmproxy import ctx

        host = (host or "").lower()
        focus = [s.strip().lower() for s in (ctx.options.game_focus or "").split(",") if s.strip()]
        if focus:
            return any(s in host for s in focus)
        noise = [s.strip().lower() for s in (ctx.options.game_noise or "").split(",") if s.strip()]
        return not any(s in host for s in noise)

    @staticmethod
    def _headers_dict(headers) -> dict:
        out = {}
        try:
            for key, value in headers.items(multi=True):
                if key in out:
                    out[key] = out[key] + ", " + value
                else:
                    out[key] = value
        except Exception:
            try:
                out = dict(headers)
            except Exception:
                out = {}
        return out

    @staticmethod
    def _tls_peer(data):
        sni = None
        address = None
        context = getattr(data, "context", None)
        if context is not None:
            server = getattr(context, "server", None)
            if server is not None:
                sni = getattr(server, "sni", None)
                address = getattr(server, "address", None)
            if not sni:
                client = getattr(context, "client", None)
                if client is not None:
                    sni = getattr(client, "sni", None)
        if sni:
            return str(sni)
        if address:
            try:
                return "%s:%s" % (address[0], address[1])
            except Exception:
                return str(address)
        return "unknown"

    # -- traffic hooks -----------------------------------------------------

    def response(self, flow: http.HTTPFlow):
        from mitmproxy import ctx

        self._seq += 1
        seq = self._seq
        request = flow.request
        response = flow.response

        request_body = describe_body(request.content or b"", request.headers)
        response_body = describe_body(response.content or b"", response.headers)

        duration_ms = None
        try:
            if response.timestamp_end and request.timestamp_start:
                duration_ms = round((response.timestamp_end - request.timestamp_start) * 1000)
        except Exception:
            pass

        record = {
            "seq": seq,
            "kind": "http",
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "method": request.method,
            "scheme": request.scheme,
            "host": request.pretty_host,
            "port": request.port,
            "path": request.path,
            "url": request.pretty_url,
            "http_version": response.http_version,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "request": {"headers": self._headers_dict(request.headers), "body": request_body},
            "response": {"headers": self._headers_dict(response.headers), "body": response_body},
        }
        self._write(record)

        if not self._console_allows(request.pretty_host):
            return

        limit = ctx.options.game_preview
        timing = ""
        if duration_ms is not None:
            timing = " %d ms" % duration_ms

        lines = [
            "[#%d] %s %s%s" % (seq, request.method, response.status_code, timing),
            "      %s" % request.pretty_url,
        ]
        sent = preview_body(request_body, limit)
        if sent:
            lines.append("   -> %s  %s" % (_human_size(request_body["size"]), sent))
        received = preview_body(response_body, limit)
        if received:
            lines.append("   <- %s  %s" % (_human_size(response_body["size"]), received))
        logging.info("\n".join(lines))

    def error(self, flow: http.HTTPFlow):
        message = str(getattr(flow.error, "msg", flow.error))
        host = getattr(flow.request, "pretty_host", "unknown")
        self._write(
            {
                "kind": "http_error",
                "time": datetime.now().isoformat(timespec="milliseconds"),
                "host": host,
                "url": getattr(flow.request, "pretty_url", None),
                "error": message,
            }
        )
        if self._console_allows(host):
            logging.warning("[error] %s  %s" % (host, message))

    def websocket_message(self, flow: http.HTTPFlow):
        if not flow.websocket or not flow.websocket.messages:
            return
        message = flow.websocket.messages[-1]
        raw = message.content
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        described = describe_body(raw, flow.request.headers)
        direction = "client->server" if message.from_client else "server->client"
        host = flow.request.pretty_host
        self._write(
            {
                "kind": "websocket",
                "time": datetime.now().isoformat(timespec="milliseconds"),
                "host": host,
                "url": flow.request.pretty_url,
                "direction": direction,
                "body": described,
            }
        )
        if self._console_allows(host):
            from mitmproxy import ctx

            arrow = "->" if message.from_client else "<-"
            logging.info(
                "[ws %s] %s  %s" % (arrow, host, preview_body(described, ctx.options.game_preview))
            )

    # Raw TCP, for game servers that speak their own protocol on their own port
    # rather than HTTP. Reached through reverse mode, see scripts\start-reverse.ps1.

    @staticmethod
    def _tcp_peer(flow) -> str:
        try:
            address = flow.server_conn.address
            return "%s:%s" % (address[0], address[1])
        except Exception:
            return "unknown"

    def tcp_start(self, flow):
        peer = self._tcp_peer(flow)
        self._write(
            {
                "kind": "tcp_start",
                "time": datetime.now().isoformat(timespec="milliseconds"),
                "host": peer,
            }
        )
        logging.info("[tcp] connection opened to %s" % peer)

    def tcp_message(self, flow):
        if not flow.messages:
            return
        from mitmproxy import ctx

        message = flow.messages[-1]
        raw = message.content
        if not isinstance(raw, bytes):
            raw = str(raw).encode("utf-8", "replace")
        described = describe_body(raw, {})
        peer = self._tcp_peer(flow)
        self._seq += 1
        self._write(
            {
                "seq": self._seq,
                "kind": "tcp_message",
                "time": datetime.now().isoformat(timespec="milliseconds"),
                "host": peer,
                "direction": "client->server" if message.from_client else "server->client",
                "body": described,
            }
        )
        arrow = "->" if message.from_client else "<-"
        logging.info(
            "[tcp %s] %s  %s  %s"
            % (arrow, peer, _human_size(described.get("size", 0)),
               preview_body(described, ctx.options.game_preview))
        )

    def tcp_error(self, flow):
        peer = self._tcp_peer(flow)
        message = str(getattr(flow, "error", ""))
        self._write(
            {
                "kind": "tcp_error",
                "time": datetime.now().isoformat(timespec="milliseconds"),
                "host": peer,
                "error": message,
            }
        )
        logging.warning("[tcp error] %s  %s" % (peer, message))

    def tls_failed_client(self, data):
        self._record_tls_failure(data, "client")

    def tls_failed_server(self, data):
        self._record_tls_failure(data, "server")

    def _record_tls_failure(self, data, side: str):
        host = self._tls_peer(data)
        self._tls_failures[host] = self._tls_failures.get(host, 0) + 1
        detail = None
        connection = getattr(data, "conn", None)
        if connection is not None:
            detail = getattr(connection, "error", None)
        self._write(
            {
                "kind": "tls_failed",
                "time": datetime.now().isoformat(timespec="milliseconds"),
                "side": side,
                "host": host,
                "error": detail,
            }
        )
        # Only shout about the first few; a pinned host retries endlessly.
        if self._tls_failures[host] <= 3:
            logging.warning(
                "[tls] handshake failed with %s (%s side)%s"
                % (host, side, "" if not detail else " - %s" % detail)
            )


addons = [GameApiLogger()]
