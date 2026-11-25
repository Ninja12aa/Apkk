"""Tu código pasa primero por la pasarela (que cambia la huella)."""
import requests
from urllib.parse import quote

GATEWAY = "http://127.0.0.1:8080/fetch?url="

def fetch(url, **kw):
    return requests.request(kw.pop("method", "GET"), GATEWAY + quote(url, safe=""), timeout=40, **kw)

if __name__ == "__main__":
    print("IP:", fetch("https://api.ipify.org/").text)
    print(fetch("https://tls.browserleaks.com/json").text[:400])
