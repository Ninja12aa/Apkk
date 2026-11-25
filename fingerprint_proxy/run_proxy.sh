#!/usr/bin/env bash
# Arranca el cambiador de huella en 127.0.0.1:8080
cd "$(dirname "$0")"
exec mitmdump -s impersonate_addon.py --listen-host 127.0.0.1 -p "${PORT:-8080}"
