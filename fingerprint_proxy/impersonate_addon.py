"""Addon de mitmproxy: rehace cada petición con la huella TLS/HTTP2 de un navegador.

Variables de entorno:
  IMPERSONATE     versión a emular (por defecto chrome124)
  UPSTREAM_PROXY  proxy opcional, p. ej. http://usuario:clave@host:puerto
"""
import os

from curl_cffi import requests
from mitmproxy import http

IMPERSONATE = os.getenv("IMPERSONATE", "chrome124")
UPSTREAM = os.getenv("UPSTREAM_PROXY")

session = requests.Session(impersonate=IMPERSONATE)

# El cliente original no debe contradecir la huella: se descartan estas cabeceras
SKIP_REQ = {"host", "content-length", "connection", "proxy-connection",
            "transfer-encoding", "accept-encoding", "user-agent"}
SKIP_RESP = {"content-encoding", "content-length", "transfer-encoding", "connection"}


def request(flow: http.HTTPFlow) -> None:
    headers = {
        k: v for k, v in flow.request.headers.items()
        if k.lower() not in SKIP_REQ and not k.lower().startswith("sec-ch-")
    }
    try:
        r = session.request(
            flow.request.method,
            flow.request.pretty_url,
            headers=headers,
            data=flow.request.content or None,
            allow_redirects=False,
            timeout=30,
            proxies={"http": UPSTREAM, "https": UPSTREAM} if UPSTREAM else None,
        )
    except Exception as e:  # error de red: lo devolvemos como 502
        flow.response = http.Response.make(502, f"fingerprint_proxy error: {e}".encode())
        return
    resp_headers = [(k, v) for k, v in r.headers.items() if k.lower() not in SKIP_RESP]
    flow.response = http.Response.make(r.status_code, r.content, resp_headers)
