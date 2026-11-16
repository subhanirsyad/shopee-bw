@echo off
rem Jalan di laptop ini saja, tanpa login Google.
cd /d "%~dp0"
set SHOPEE_BW_LOKAL=1
python -m streamlit run app.py
pause
