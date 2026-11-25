# Pasarela de huella para Termux

```bash
bash setup_termux.sh                     # instala dependencias (una vez)
export PROXIES="http://USUARIO:CLAVE@gw.dataimpulse.com:823"   # opcional; varios separados por coma
python gateway_pro.py                    # arranca en 127.0.0.1:8080
python client_pro_example.py             # en otra sesion de Termux
```
- `/stats` muestra que huellas funcionan en cada sitio. `state.json` guarda lo aprendido.
- Si `pip install curl-cffi` falla en Termux, prueba `pkg install python-cryptography` y reintenta, o usa la version en un PC/servidor.
- No guardes credenciales en el repositorio: usa variables de entorno.

## Soporte JavaScript (navegador real)
La pasarela prueba primero con las huellas (rapido). Si todo falla, abre la pagina en Chromium
para que ejecute el JavaScript y resuelva el desafio; las cookies se reutilizan despues.

- `JS_MODE=auto` (por defecto) | `always` | `off`. Por peticion: `&js=1` fuerza navegador, `&js=0` lo desactiva.
- `&wait_for=<selector css>` y `&wait_ms=2000` esperan a que cargue contenido dinamico.
- Solo GET pasa por el navegador. Cada peticion con navegador tarda varios segundos.
- Instalacion: `pip install playwright` y un Chromium (`BROWSER_PATH=/ruta/a/chromium`).
  En PC/servidor: `playwright install chromium`.
- **Termux (sin probar):** Playwright no soporta Android oficialmente. Puedes intentar
  `pkg install tur-repo && pkg install chromium` y `pip install playwright` con `BROWSER_PATH`;
  si no compila, ejecuta la pasarela en un PC o servidor y usala desde el movil por red local.
- Sin navegador instalado, la pasarela sigue funcionando solo con huellas (`/stats` muestra `browser_available`).
- Ver `/stats` para el estado. Headless detectable: algunos sitios aun lo bloquearan.
