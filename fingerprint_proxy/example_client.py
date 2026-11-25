"""Tu código normal, pero pasando primero por el cambiador de huella."""
import os
import requests

PROXY = "http://127.0.0.1:8080"
CA = os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.pem")

s = requests.Session()
s.proxies = {"http": PROXY, "https": PROXY}
s.verify = CA  # confía en el CA de mitmproxy (se crea al arrancar el proxy)

r = s.get("https://tls.browserleaks.com/json", timeout=30)
print(r.status_code)
print(r.text[:500])
