"""Pasarela local con huella de navegador (sin mitmproxy, solo curl_cffi).

Arranque:
  UPSTREAM_PROXY="http://USUARIO:CLAVE@gw.dataimpulse.com:823" IMPERSONATE=chrome124 python gateway.py

Uso desde tu código (cualquier lenguaje o librería):
  GET  http://127.0.0.1:8080/fetch?url=https%3A%2F%2Fapi.ipify.org%2F
  POST http://127.0.0.1:8080/fetch?url=...   (el cuerpo y las cabeceras se reenvían)
"""
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from curl_cffi import requests

IMPERSONATE = os.getenv("IMPERSONATE", "chrome124")
UPSTREAM = os.getenv("UPSTREAM_PROXY")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8080"))

SKIP_REQ = {"host", "content-length", "connection", "accept-encoding", "user-agent",
            "transfer-encoding", "proxy-connection"}
SKIP_RESP = {"content-encoding", "content-length", "transfer-encoding", "connection"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _handle(self):
        qs = parse_qs(urlparse(self.path).query)
        target = (qs.get("url") or [None])[0]
        if not target:
            return self._send(400, b"Falta el parametro ?url=")
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in SKIP_REQ and not k.lower().startswith("sec-ch-")}
        try:
            r = requests.request(
                self.command, target, headers=headers, data=body,
                impersonate=IMPERSONATE, allow_redirects=True, timeout=30,
                proxies={"http": UPSTREAM, "https": UPSTREAM} if UPSTREAM else None,
            )
        except Exception as e:
            return self._send(502, f"error: {e}".encode())
        self._send(r.status_code, r.content,
                   [(k, v) for k, v in r.headers.items() if k.lower() not in SKIP_RESP])

    def _send(self, status, body, headers=()):
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _handle

    def log_message(self, fmt, *args):
        sys.stderr.write("%s\n" % (fmt % args))


if __name__ == "__main__":
    print(f"Pasarela en http://{HOST}:{PORT}  huella={IMPERSONATE}  proxy={'si' if UPSTREAM else 'no'}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
