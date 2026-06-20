#!/usr/bin/env python3
"""
CryptoChat relay server  --  ZERO external dependencies (Python 3.8+ stdlib only).

SECURITY MODEL
--------------
This server is a "dumb pipe". It does the following and NOTHING else:

  1. Serves the static client files (index.html, app.js, styles.css).
  2. Accepts WebSocket connections.
  3. Relays opaque encrypted blobs between clients that joined the same room code.

The server NEVER sees:
  - your passphrase / encryption key
  - the plaintext of any message

All encryption and decryption happens in the browser (Web Crypto API, AES-256-GCM).
The server only ever handles ciphertext, so it physically cannot read your messages,
and neither can your ISP or anyone intercepting the traffic (run it behind TLS / wss://
in production -- see README for a one-line reverse proxy).

Run:
    python3 server.py            # listens on 0.0.0.0:8765
    PORT=9000 python3 server.py  # custom port
"""

import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time
from collections import defaultdict

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# room_code -> set of client connection objects
rooms = defaultdict(set)
rooms_lock = threading.Lock()

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".ico": "image/x-icon",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}


# --------------------------------------------------------------------------- #
# WebSocket frame helpers (RFC 6455)
# --------------------------------------------------------------------------- #
class WSClient:
    """Wraps a single accepted socket and provides framed send/recv."""

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.room = None
        self.send_lock = threading.Lock()
        self.open = True

    # ---- low level recv of exactly n bytes ----
    def _recv_exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("peer closed")
            buf.extend(chunk)
        return bytes(buf)

    def read_frame(self):
        """Return (opcode, payload_bytes) or None on close."""
        b1, b2 = self._recv_exact(2)
        opcode = b1 & 0x0F
        masked = b2 & 0x80
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        # Reject absurdly large frames (defensive; 16 MiB cap)
        if length > 16 * 1024 * 1024:
            raise ConnectionError("frame too large")
        mask = self._recv_exact(4) if masked else b"\x00\x00\x00\x00"
        data = bytearray(self._recv_exact(length))
        if masked:
            for i in range(length):
                data[i] ^= mask[i % 4]
        return opcode, bytes(data)

    def send_text(self, text):
        self._send_frame(0x1, text.encode("utf-8"))

    def send_close(self):
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass

    def send_pong(self, payload=b""):
        self._send_frame(0xA, payload)

    def _send_frame(self, opcode, payload):
        if not self.open:
            return
        header = bytearray()
        header.append(0x80 | opcode)  # FIN + opcode
        n = len(payload)
        if n < 126:
            header.append(n)
        elif n < 65536:
            header.append(126)
            header.extend(struct.pack(">H", n))
        else:
            header.append(127)
            header.extend(struct.pack(">Q", n))
        with self.send_lock:
            self.conn.sendall(bytes(header) + payload)


# --------------------------------------------------------------------------- #
# HTTP / static serving + WS upgrade
# --------------------------------------------------------------------------- #
def serve_static(conn, path):
    if path == "/" or path == "":
        path = "/index.html"
    # prevent path traversal
    safe = os.path.normpath(path).lstrip("/")
    full = os.path.join(STATIC_DIR, safe)
    if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
        body = b"404 Not Found"
        conn.sendall(
            b"HTTP/1.1 404 Not Found\r\nContent-Length: %d\r\n"
            b"Content-Type: text/plain\r\n\r\n%s" % (len(body), body)
        )
        return
    ext = os.path.splitext(full)[1]
    ctype = MIME.get(ext, "application/octet-stream")
    with open(full, "rb") as f:
        body = f.read()
    headers = (
        "HTTP/1.1 200 OK\r\n"
        f"Content-Type: {ctype}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Cache-Control: no-store\r\n"
        "X-Content-Type-Options: nosniff\r\n"
        "\r\n"
    ).encode("utf-8")
    conn.sendall(headers + body)


def parse_headers(raw):
    lines = raw.split("\r\n")
    request_line = lines[0]
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return request_line, headers


def do_ws_handshake(conn, headers):
    key = headers.get("sec-websocket-key")
    if not key:
        return False
    accept = base64.b64encode(
        hashlib.sha1((key + WS_MAGIC).encode()).digest()
    ).decode()
    resp = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    conn.sendall(resp.encode())
    return True


def broadcast(room, sender, text):
    with rooms_lock:
        peers = list(rooms.get(room, set()))
    for p in peers:
        if p is sender:
            continue
        try:
            p.send_text(text)
        except Exception:
            pass


def room_count(room):
    with rooms_lock:
        return len(rooms.get(room, set()))


def handle_ws(client: WSClient):
    """Main per-connection loop after upgrade."""
    try:
        while True:
            opcode, payload = client.read_frame()
            if opcode == 0x8:  # close
                break
            elif opcode == 0x9:  # ping
                client.send_pong(payload)
                continue
            elif opcode == 0xA:  # pong
                continue
            elif opcode not in (0x1, 0x2):
                continue

            try:
                msg = json.loads(payload.decode("utf-8"))
            except Exception:
                continue

            mtype = msg.get("type")

            if mtype == "join":
                room = str(msg.get("room", ""))[:128]
                if not room:
                    continue
                with rooms_lock:
                    # leave previous room if any
                    if client.room and client in rooms.get(client.room, set()):
                        rooms[client.room].discard(client)
                    client.room = room
                    rooms[room].add(client)
                n = room_count(room)
                # tell the joiner the current occupancy
                client.send_text(json.dumps({"type": "joined", "room": room, "count": n}))
                # tell everyone the new presence count
                broadcast(room, None, json.dumps({"type": "presence", "count": n}))

            elif mtype == "msg":
                # The server relays the ENCRYPTED blob verbatim. It has no idea
                # what's inside. 'payload' here is the client's base64 ciphertext.
                if not client.room:
                    continue
                relay = json.dumps({
                    "type": "msg",
                    "payload": msg.get("payload", ""),
                    "ts": int(time.time() * 1000),
                })
                broadcast(client.room, client, relay)

            elif mtype == "ping":
                client.send_text(json.dumps({"type": "pong"}))

    except (ConnectionError, OSError):
        pass
    finally:
        client.open = False
        room = client.room
        with rooms_lock:
            if room and client in rooms.get(room, set()):
                rooms[room].discard(client)
                if not rooms[room]:
                    del rooms[room]
        if room:
            broadcast(room, None, json.dumps({"type": "presence", "count": room_count(room)}))
        try:
            client.send_close()
            client.conn.close()
        except Exception:
            pass


def handle_conn(conn, addr):
    try:
        conn.settimeout(10)
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = conn.recv(4096)
            if not chunk:
                conn.close()
                return
            raw += chunk
            if len(raw) > 65536:
                conn.close()
                return
        head = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1")
        request_line, headers = parse_headers(head)
        parts = request_line.split(" ")
        method = parts[0] if parts else "GET"
        path = parts[1] if len(parts) > 1 else "/"

        upgrade = headers.get("upgrade", "").lower()
        if path == "/ws" and upgrade == "websocket":
            conn.settimeout(None)
            if do_ws_handshake(conn, headers):
                client = WSClient(conn, addr)
                handle_ws(client)
            return
        else:
            serve_static(conn, path)
            conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(128)
    print(f"CryptoChat relay running -> http://{HOST}:{PORT}  (open this in your browser)")
    print("Server relays ciphertext only. It cannot read your messages.")
    try:
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(target=handle_conn, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
