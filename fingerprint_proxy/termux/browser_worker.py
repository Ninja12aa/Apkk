"""Renderizado con navegador real (Chromium via Playwright) para paginas con JavaScript.

Un unico hilo posee el navegador (la API sincrona de Playwright no es multihilo) y
atiende los trabajos por una cola. Se mantiene un contexto por (sitio, proxy), asi las
cookies de un desafio ya resuelto se reutilizan en las siguientes peticiones.

Variables de entorno:
  BROWSER_PATH   ruta al ejecutable de Chromium/Chrome (opcional)
  JS_TIMEOUT     segundos maximos esperando que el desafio termine (25)
  BROWSER_LOCALE idioma del navegador (en-US)
  MAX_CONTEXTS   contextos abiertos como maximo (20)
"""
import os
import queue
import threading
from collections import OrderedDict
from concurrent.futures import Future
from urllib.parse import urlparse

JS_TIMEOUT = float(os.getenv("JS_TIMEOUT", "25"))
LOCALE = os.getenv("BROWSER_LOCALE", "en-US")
MAX_CONTEXTS = int(os.getenv("MAX_CONTEXTS", "20"))

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
"""


def parse_proxy(proxy):
    if not proxy:
        return None
    u = urlparse(proxy)
    cfg = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
    if u.username:
        cfg["username"] = u.username
        cfg["password"] = u.password or ""
    return cfg


class BrowserWorker:
    def __init__(self, is_challenge):
        self.is_challenge = is_challenge  # callable(bytes) -> bool
        self.q = queue.Queue()
        self.thread = None
        self.start_error = None
        self._start_lock = threading.Lock()
        self._ready = threading.Event()

    def available(self):
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    def render(self, url, proxy=None, wait_for=None, wait_ms=0, timeout=None):
        """Devuelve dict(status, body, content_type, url, cleared). Lanza excepcion si falla."""
        self._ensure_started()
        if self.start_error:
            raise RuntimeError(f"navegador no disponible: {self.start_error}")
        fut = Future()
        self.q.put((fut, url, proxy, wait_for, wait_ms, timeout or JS_TIMEOUT))
        return fut.result(timeout=(timeout or JS_TIMEOUT) + 60)

    def _ensure_started(self):
        with self._start_lock:
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()
        self._ready.wait(timeout=60)

    def _run(self):
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            kwargs = {"headless": True, "args": LAUNCH_ARGS}
            if os.getenv("BROWSER_PATH"):
                kwargs["executable_path"] = os.environ["BROWSER_PATH"]
            browser = pw.chromium.launch(**kwargs)
            major = browser.version.split(".")[0]
            ua = (f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")
        except Exception as e:
            self.start_error = str(e)
            self._ready.set()
            return
        self._ready.set()

        contexts = OrderedDict()

        def get_ctx(key, proxy):
            if key in contexts:
                contexts.move_to_end(key)
                return contexts[key]
            while len(contexts) >= MAX_CONTEXTS:
                _, old = contexts.popitem(last=False)
                try:
                    old.close()
                except Exception:
                    pass
            ctx = browser.new_context(user_agent=ua, locale=LOCALE, proxy=parse_proxy(proxy),
                                      viewport={"width": 1366, "height": 768})
            ctx.add_init_script(STEALTH_JS)
            contexts[key] = ctx
            return ctx

        while True:
            job = self.q.get()
            if job is None:
                break
            fut, url, proxy, wait_for, wait_ms, timeout = job
            try:
                key = (urlparse(url).netloc, proxy)
                fut.set_result(self._render(get_ctx(key, proxy), url, wait_for, wait_ms, timeout))
            except Exception as e:
                fut.set_exception(e)

    def _render(self, ctx, url, wait_for, wait_ms, timeout):
        page = ctx.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            status = resp.status if resp else 200
            ctype = (resp.headers.get("content-type", "") if resp else "") or "text/html"
            raw = resp.body() if resp else b""
            cleared = False
            elapsed = 0.0
            # esperar a que termine el desafio JS (la pagina se recarga o cambia sola)
            while elapsed < timeout:
                html = page.content().encode()
                if not self.is_challenge(html):
                    break
                page.wait_for_timeout(1000)
                elapsed += 1.0
                cleared = True
            else:
                html = page.content().encode()
            solved = cleared and not self.is_challenge(html)
            if wait_for:
                page.wait_for_selector(wait_for, timeout=int(timeout * 1000))
            if wait_ms:
                page.wait_for_timeout(int(wait_ms))
            html = page.content().encode()
            body = html
            if "html" not in ctype and not solved and raw:  # JSON/otros: cuerpo original
                body = raw
            if solved or (not self.is_challenge(html) and status in (403, 503)):
                status = 200
            return {"status": status, "body": body, "content_type": ctype,
                    "url": page.url, "cleared": solved,
                    "blocked": self.is_challenge(html)}
        finally:
            try:
                page.close()
            except Exception:
                pass
