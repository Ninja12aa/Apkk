#!/data/data/com.termux/files/usr/bin/bash
# Instalación en Termux
set -e
pkg update -y
pkg install -y python clang rust make libffi openssl git
pip install --upgrade pip
pip install curl-cffi
python -c "import curl_cffi; print('curl_cffi', curl_cffi.__version__)"
