"""Pasarela completa con huella de navegador (solo curl_cffi + libreria estandar).

Que hace:
  - Rota entre varias huellas (chrome/safari/firefox/edge) y APRENDE cuales funcionan
    por sitio (puntuacion con exploracion), guardando el estado en state.json.
  - Cookies persistentes por (sitio, huella, proxy): mantiene la sesion coherente.
  - Rotacion de proxies con IP "pegajosa" por sitio; si un proxy falla, pasa al siguiente.
  - Reintentos con espera exponencial + jitter, respeta Retry-After en 429.
  - Detecta bloqueos (403/429/503 y paginas de desafio/captcha) aunque devuelvan 200.
  - Pausa minima aleatoria entre peticiones al mismo sitio (ritmo humano).
  - Cabeceras coherentes: descarta User-Agent y sec-ch-* del cliente para no
    contradecir la huella emulada.

Variables de entorno:
  PROXIES        lista separada por comas: http://u:p@host:puerto,http://u:p@host2:puerto
  PROXIES_FILE   fichero con un proxy por linea (alternativa)
  PROFILES       huellas en orden de preferencia (por defecto chrome124, safari18_0, safari17_0)
  MAX_TRIES      intentos por peticion (por defecto 5)
  MIN_DELAY / MAX_DELAY  pausa entre peticiones al mismo sitio, en segundos (0.3 / 1.2)
  JS_MODE        auto (por defecto: navegador si todo falla) | always | off
  BROWSER_PATH   ejecutable de Chromium (opcional); JS_TIMEOUT segundos para el desafio
  HOST / PORT    127.0.0.1 / 8080
  STATE_FILE     state.json

Uso:
  GET|POST http://127.0.0.1:8080/fetch?url=<URL-codificada>[&profile=chrome124][&tries=3]
                 [&js=1 fuerza navegador | js=0 lo desactiva][&wait_for=<selector css>][&wait_ms=2000]
  GET      http://127.0.0.1:8080/stats
  GET      http://127.0.0.1:8080/health
Las respuestas incluyen X-Gateway-Profile, X-Gateway-Tries y X-Gateway-Blocked.
"""
import json
import os
import random
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from curl_cffi import requests

from browser_worker import BrowserWorker

try:  # proxy base: proxy_config.py (no se sube a git); PROXIES/PROXIES_FILE lo sustituyen
    from proxy_config import PROXIES as CONFIG_PROXIES
except ImportError:
    CONFIG_PROXIES = []

DEFAULT_PROFILES = ["chrome124", "safari18_0", "safari17_0"]
PROFILES = [p.strip() for p in os.getenv("PROFILES", ",".join(DEFAULT_PROFILES)).split(",") if p.strip()]
MAX_TRIES = int(os.getenv("MAX_TRIES", "5"))
MIN_DELAY = float(os.getenv("MIN_DELAY", "0.3"))
MAX_DELAY = float(os.getenv("MAX_DELAY", "1.2"))
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8080"))
STATE_FILE = os.getenv("STATE_FILE", "state.json")
JS_MODE = os.getenv("JS_MODE", "auto")  # auto | always | off
EPSILON = 0.1  # probabilidad de probar una huella distinta a la mejor

BLOCK_STATUS = {401, 403, 407, 429, 503}
BLOCK_MARKERS = [
    b"just a moment", b"cf-chl", b"challenge-platform", b"attention required",
    b"access denied", b"pardon our interruption", b"px-captcha", b"perimeterx",
    b"incapsula", b"request unsuccessful", b"datadome", b"captcha-delivery",
    b"are you a robot", b"unusual traffic", b"_incapsula_resource",
]
SKIP_REQ = {"host", "content-length", "connection", "accept-encoding", "user-agent",
            "transfer-encoding", "proxy-connection"}
SKIP_RESP = {"content-encoding", "content-length", "transfer-encoding", "connection"}


def load_proxies():
    items = [p.strip() for p in os.getenv("PROXIES", "").split(",") if p.strip()]
    path = os.getenv("PROXIES_FILE")
    if path and os.path.exists(path):
        items += [l.strip() for l in open(path) if l.strip() and not l.startswith("#")]
    return items or list(CONFIG_PROXIES) or [None]  # None = conexion directa


PROXIES = load_proxies()
lock = threading.RLock()
bad_profiles = set()          # huellas que curl_cffi no reconoce
sessions = {}                 # (host, profile, proxy_idx) -> (Session, Lock)
last_hit = {}                 # host -> timestamp de la ultima peticion
sticky_proxy = {}             # host -> indice de proxy
proxy_cooldown = {}           # indice -> timestamp hasta el que se evita
state = {"scores": {}}        # scores[host][profile] = [ok, fail]


def load_state():
    try:
        with open(STATE_FILE) as f:
            state.update(json.load(f))
    except Exception:
        pass


def save_state():
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def record(host, profile, ok):
    with lock:
        s = state["scores"].setdefault(host, {}).setdefault(profile, [0, 0])
        s[0 if ok else 1] += 1
        save_state()


def rank(host, exclude=()):
    """Huellas ordenadas de mejor a peor para este sitio (ok+1)/(total+2)."""
    with lock:
        sc = state["scores"].get(host, {})
        cands = [p for p in PROFILES if p not in bad_profiles and p not in exclude]

        def score(p):
            ok, fail = sc.get(p, [0, 0])
            return (ok + 1) / (ok + fail + 2)

        cands.sort(key=score, reverse=True)
        if len(cands) > 1 and random.random() < EPSILON:
            i = random.randrange(1, len(cands))
            cands.insert(0, cands.pop(i))
        return cands


def pick_proxy(host, rotate=False):
    with lock:
        n = len(PROXIES)
        now = time.time()
        idx = sticky_proxy.get(host, random.randrange(n))
        if rotate or proxy_cooldown.get(idx, 0) > now:
            options = [i for i in range(n) if proxy_cooldown.get(i, 0) <= now and i != idx] or list(range(n))
            idx = random.choice(options)
        sticky_proxy[host] = idx
        return idx


def get_session(host, profile, pidx):
    key = (host, profile, pidx)
    with lock:
        if key not in sessions:
            sessions[key] = (requests.Session(impersonate=profile), threading.Lock())
        return sessions[key]


def polite_wait(host):
    with lock:
        now = time.time()
        wait = max(0.0, last_hit.get(host, 0) + random.uniform(MIN_DELAY, MAX_DELAY) - now)
        last_hit[host] = now + wait
    if wait:
        time.sleep(wait)


def looks_blocked_html(body):
    head = body[:20000].lower()
    return any(m in head for m in BLOCK_MARKERS)


browser = BrowserWorker(looks_blocked_html)


class BrowserResp:
    """Imita lo minimo de una respuesta de curl_cffi."""
    def __init__(self, d):
        self.status_code = d["status"]
        self.content = d["body"]
        self.headers = {"content-type": d["content_type"]}


def render_with_browser(url, host, wait_for=None, wait_ms=0):
    proxy = PROXIES[pick_proxy(host)]
    d = browser.render(url, proxy, wait_for, wait_ms)
    return BrowserResp(d), {"profile": "browser", "blocked": d["blocked"], "cleared": d["cleared"]}


def is_blocked(resp):
    if resp.status_code in BLOCK_STATUS:
        return True
    ctype = resp.headers.get("content-type", "")
    if "html" in ctype or "text" in ctype:
        return looks_blocked_html(resp.content)
    return False


def fetch(method, url, headers, body, forced_profile=None, tries=MAX_TRIES, js=None,
          wait_for=None, wait_ms=0):
    host = urlparse(url).netloc
    mode = js or JS_MODE  # "always" | "auto" | "off"
    can_js = method == "GET" and mode != "off" and browser.available()
    if can_js and mode == "always":
        try:
            r, info = render_with_browser(url, host, wait_for, wait_ms)
            info["tries"] = 0
            return r, info
        except Exception as e:
            return None, {"error": f"navegador: {e}", "tries": 0}
    tried, last, last_info = [], None, {}
    for attempt in range(1, tries + 1):
        profile = forced_profile or (rank(host, exclude=tried) or PROFILES)[0]
        pidx = pick_proxy(host, rotate=attempt > 1)
        proxy = PROXIES[pidx]
        sess, slock = get_session(host, profile, pidx)
        polite_wait(host)
        try:
            with slock:
                r = sess.request(method, url, headers=headers, data=body, timeout=30,
                                 allow_redirects=True,
                                 proxies={"http": proxy, "https": proxy} if proxy else None)
        except Exception as e:
            msg = str(e).lower()
            if "impersonat" in msg and ("not supported" in msg or "unknown" in msg or "invalid" in msg):
                bad_profiles.add(profile)
            else:  # fallo de red / proxy: enfria ese proxy un rato
                with lock:
                    proxy_cooldown[pidx] = time.time() + 30
            tried.append(profile)
            last_info = {"error": str(e)}
            time.sleep(min(8, 2 ** attempt * 0.25) + random.random() * 0.3)
            continue
        blocked = is_blocked(r)
        record(host, profile, not blocked)
        tried.append(profile)
        last, last_info = r, {"profile": profile, "tries": attempt, "blocked": blocked}
        if not blocked:
            return r, last_info
        # bloqueado: esperar (Retry-After en 429) y probar otra huella/proxy
        wait = min(8, 2 ** attempt * 0.25)
        if r.status_code == 429:
            try:
                wait = max(wait, min(30, float(r.headers.get("retry-after", wait))))
            except ValueError:
                pass
        time.sleep(wait + random.random() * 0.5)
    last_info.setdefault("tries", tries)
    last_info["blocked"] = True
    if can_js:  # ultimo recurso: ejecutar el JavaScript en un navegador real
        try:
            r, info = render_with_browser(url, host, wait_for, wait_ms)
            info["tries"] = last_info["tries"]
            return r, info
        except Exception as e:
            last_info["browser_error"] = str(e)
    return last, last_info


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, body, headers=()):
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, indent=2).encode(), [("Content-Type", "application/json")])

    def _handle(self):
        u = urlparse(self.path)
        if u.path == "/health":
            return self._json(200, {"ok": True})
        if u.path == "/stats":
            with lock:
                return self._json(200, {"profiles": PROFILES, "bad_profiles": sorted(bad_profiles),
                                        "proxies": len(PROXIES), "js_mode": JS_MODE,
                                        "browser_available": browser.available(), "scores": state["scores"]})
        if u.path != "/fetch":
            return self._json(404, {"error": "usa /fetch?url=..., /stats o /health"})
        qs = parse_qs(u.query)
        target = (qs.get("url") or [None])[0]
        if not target or not target.startswith(("http://", "https://")):
            return self._json(400, {"error": "falta ?url=http(s)://..."})
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in SKIP_REQ and not k.lower().startswith("sec-ch-")}
        tries = int((qs.get("tries") or [MAX_TRIES])[0])
        js = (qs.get("js") or [None])[0]
        js = {"1": "always", "0": "off"}.get(js, js)
        r, info = fetch(self.command, target, headers, body, (qs.get("profile") or [None])[0], tries,
                        js, (qs.get("wait_for") or [None])[0], int((qs.get("wait_ms") or [0])[0]))
        if r is None:
            return self._json(502, {"error": info.get("error", "sin respuesta"), **info})
        extra = [(k, v) for k, v in r.headers.items() if k.lower() not in SKIP_RESP]
        extra += [("X-Gateway-Profile", str(info.get("profile"))),
                  ("X-Gateway-Tries", str(info.get("tries"))),
                  ("X-Gateway-Blocked", "1" if info.get("blocked") else "0"),
                  ("X-Gateway-JS", "1" if info.get("profile") == "browser" else "0")]
        self._send(r.status_code, r.content, extra)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _handle

    def log_message(self, fmt, *args):
        sys.stderr.write("%s\n" % (fmt % args))


if __name__ == "__main__":
    load_state()
    print(f"Pasarela en http://{HOST}:{PORT} | huellas={len(PROFILES)} proxies={len(PROXIES) if PROXIES != [None] else 0}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
