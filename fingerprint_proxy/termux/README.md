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
