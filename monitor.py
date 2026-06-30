"""
Monitor de citas — Consulado de España en La Habana

VERSIÓN 6 - UNDETECTED CHROMEDRIVER (SOLUCIÓN FINAL)
- undetected-chromedriver: bypass de Cloudflare v2
- Selenium con Chrome real (no headless detectable)
- Anti-detección profunda
"""

import asyncio
import os
import sys
import traceback
import random
import time
from pathlib import Path

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import undetected_chromedriver as uc

WIDGET_URL = (
    "https://www.citaconsular.es/es/hosteds/widgetdefault/"
    "2686d3b68dc9e0ba3c6a20437e9cc7"
)
PUBLIC_URL = (
    "https://www.exteriores.gob.es/Consulados/lahabana/es/ServiciosConsulares/"
    "Paginas/index.aspx?scco=Cuba&scd=166&scca=Visados"
    "&scs=Visados+Nacionales+-+Visado+de+residencia+de+familiares"
    "+de+personas+de+nacionalidad+espa%c3%b1ola"
)
STATE_FILE = Path("state.txt")

WIDGET_LOADED_MARKERS = [
    "bookitit",
    "Bookitit",
    "Consulado General de España",
    "Cancelar o consultar mis reservas",
]

NO_AVAILABILITY_MARKERS = [
    "No hay horas disponibles",
    "no hay horas disponibles",
    "Inténtelo de nuevo dentro de unos días",
]

CLOUDFLARE_MARKERS = [
    "challenges.cloudflare.com",
    "cf-challenge",
    "Verifying you are human",
    "Just a moment",
    "Enable JavaScript",
]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

def log(msg: str) -> None:
    print(f"[BOT] {msg}", flush=True)

def notify_text(message: str) -> None:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
            },
            timeout=15,
        )
        log("✓ Mensaje enviado a Telegram")
    except Exception as e:
        log(f"✗ Error Telegram: {e}")

def notify_with_photo(message: str, photo_path: str) -> None:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    if not Path(photo_path).exists():
        notify_text(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "caption": message,
                    "parse_mode": "Markdown",
                },
                files={"photo": f},
                timeout=30,
            )
        log("✓ Foto enviada")
    except Exception as e:
        log(f"✗ Error foto: {e}")
        notify_text(message)

def read_state() -> str:
    if STATE_FILE.exists():
        return STATE_FILE.read_text().strip()
    return "unknown"

def write_state(value: str) -> None:
    STATE_FILE.write_text(value)

def check_availability() -> tuple[str, str, str]:
    """Usar undetected-chromedriver para bypass"""
    
    log("🔓 Iniciando undetected-chromedriver...")
    
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-sync")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    
    driver = None
    try:
        driver = uc.Chrome(options=options, version_main=None)
        
        log(f"🌐 Navegando a {WIDGET_URL}")
        driver.get(WIDGET_URL)
        
        log("⏳ Esperando Cloudflare (40s)...")
        time.sleep(40)
        
        # Screenshot 1
        driver.save_screenshot("step1_after_load.png")
        log("✓ Screenshot 1")
        
        # Buscar Continue
        log("🔘 Buscando botón Continue...")
        try:
            wait = WebDriverWait(driver, 10)
            buttons = [
                (By.XPATH, "//button[contains(text(), 'Continuar')]"),
                (By.XPATH, "//a[contains(text(), 'Continuar')]"),
                (By.XPATH, "//button[contains(text(), 'Continue')]"),
                (By.XPATH, "//input[@value*='ontinuar']"),
            ]
            
            for by, xpath in buttons:
                try:
                    btn = wait.until(EC.element_to_be_clickable((by, xpath)))
                    time.sleep(random.uniform(1, 2))
                    btn.click()
                    log("✓ Click en Continue")
                    time.sleep(3)
                    break
                except:
                    continue
        except Exception as e:
            log(f"⚠️ No se encontró Continue: {e}")
        
        log("⏳ Esperando widget (40s)...")
        time.sleep(40)
        
        # Screenshot 2
        driver.save_screenshot("step2_final.png")
        log("✓ Screenshot 2")
        
        # Obtener HTML
        full_content = driver.page_source
        log(f"✓ HTML: {len(full_content)} chars")
        
        # Analizar
        widget_loaded = any(m in full_content for m in WIDGET_LOADED_MARKERS)
        no_disponible = any(m in full_content for m in NO_AVAILABILITY_MARKERS)
        cloudflare_blocking = any(m in full_content for m in CLOUDFLARE_MARKERS)
        
        log(f"📊 Widget: {widget_loaded}")
        log(f"📊 Sin citas: {no_disponible}")
        log(f"📊 CF bloquea: {cloudflare_blocking}")
        
        if not widget_loaded:
            estado = "blocked" if cloudflare_blocking else "unknown"
        else:
            estado = "unavailable" if no_disponible else "available"
        
        return estado, full_content, "step2_final.png"
        
    except Exception as e:
        log(f"❌ Error: {e}")
        traceback.print_exc()
        raise
        
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

def main() -> int:
    try:
        estado, content, screenshot = check_availability()
    except Exception as e:
        err = f"⚠️ *Error crítico*\n\n`{type(e).__name__}: {e}`"
        log(err)
        if read_state() != "error":
            notify_text(err)
            write_state("error")
        return 1
    
    prev = read_state()
    log(f"Estado: {prev} → {estado}")
    
    if estado == "available":
        if prev != "available":
            msg = (
                "🎉 *¡CITAS DISPONIBLES!*\n\n"
                "Consulado: La Habana\n\n"
                f"👉 [RESERVAR YA]({WIDGET_URL})"
            )
            notify_with_photo(msg, screenshot)
        write_state("available")
    
    elif estado == "unavailable":
        write_state("unavailable")
    
    elif estado == "blocked":
        log("Cloudflare bloqueó - sin cambiar estado")
    
    Path("last_run.html").write_text(content[:300_000])
    return 0

if __name__ == "__main__":
    sys.exit(main())
