"""Compara la huella de cada perfil de curl_cffi con una captura real de Chrome 158 (Android).

Uso:  python compare_fingerprint.py            (usa proxy_config.py si existe)
      PROXY= python compare_fingerprint.py     (PROXY vacio = conexion directa)
      PROFILES=chrome152,chrome131_android,chrome124 python compare_fingerprint.py
Muestra, por perfil, si coinciden JA4 (completo y por partes) y la huella HTTP/2 de Akamai.
"""
import os
from curl_cffi import requests
from curl_cffi.requests import BrowserType

REF_JA4 = "t13d1517h2_8daaf6152771_cb7bf5808d99"
REF_AKAMAI = "52d84b11737d980aef856699f885ca86"
URL = "https://tls.peet.ws/api/all"

try:
    from proxy_config import PROXIES
    default_proxy = PROXIES[0] if PROXIES else ""
except ImportError:
    default_proxy = ""
proxy = os.getenv("PROXY", default_proxy)
proxies = {"http": proxy, "https": proxy} if proxy else None

wanted = os.getenv("PROFILES")
if wanted:
    profiles = [p.strip() for p in wanted.split(",")]
else:
    allp = [b.value for b in BrowserType]
    profiles = [p for p in allp if p.startswith(("chrome12", "chrome13", "chrome14", "chrome15", "safari18", "safari26"))]
    profiles += [p for p in allp if "android" in p and p not in profiles]

ref = REF_JA4.split("_")
print(f"{'perfil':22} {'JA4':5} {'cifrados':9} {'extens.':8} {'HTTP2':6} ja4")
for p in profiles:
    try:
        d = requests.get(URL, impersonate=p, proxies=proxies, timeout=30).json()
        ja4 = d["tls"]["ja4"]
        a = ja4.split("_")
        h2 = d["http2"]["akamai_fingerprint_hash"]
        ok = lambda b: "SI" if b else "no"
        print(f"{p:22} {ok(ja4 == REF_JA4):5} {ok(a[1] == ref[1]):9} {ok(a[2] == ref[2]):8} {ok(h2 == REF_AKAMAI):6} {ja4}")
    except Exception as e:
        print(f"{p:22} error: {str(e)[:60]}")
