"""Tu codigo pasando por la pasarela completa (gateway_pro.py)."""
import requests
from urllib.parse import quote

GATEWAY = "http://127.0.0.1:8080"

def fetch(url, method="GET", **kw):
    r = requests.request(method, f"{GATEWAY}/fetch?url={quote(url, safe='')}", timeout=120, **kw)
    return r

if __name__ == "__main__":
    r = fetch("https://api.ipify.org/")
    print("IP:", r.text, "| huella:", r.headers.get("X-Gateway-Profile"),
          "| intentos:", r.headers.get("X-Gateway-Tries"), "| bloqueado:", r.headers.get("X-Gateway-Blocked"))
