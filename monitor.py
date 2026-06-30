"""
Monitor de citas — Consulado de España en La Habana
VERSIÓN FINAL - CON IFRAME DETECTION
"""

import asyncio
import os
import sys
import traceback
import random
from pathlib import Path

import requests
from playwright.async_api import async_playwright

WIDGET_URL = "https://www.citaconsular.es/es/hosteds/widgetdefault/2686d3b68dc9e0ba3c6a20437e9cc7"
PUBLIC_URL = "https://www.exteriores.gob.es/Consulados/lahabana/es/ServiciosConsulares/Paginas/index.aspx?scco=Cuba&scd=166&scca=Visados&scs=Visados+Nacionales+-+Visado+de+residencia+de+familiares+de+personas+de+nacionalidad+espa%c3%b1ola"
STATE_FILE = Path("state.txt")

WIDGET_LOADED_MARKERS = ["bookitit", "Bookitit", "Consulado General de España", "Cancelar o consultar"]
NO_AVAILABILITY_MARKERS = ["No hay horas disponibles", "no hay horas disponibles", "Inténtelo de nuevo"]
CLOUDFLARE_MARKERS = ["challenges.cloudflare.com", "cf-challenge", "Verifying you are human", "Just a moment"]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

STEALTH_JS = """
(() => {
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'vendor', {get: () => 'Google Inc.'});
    Object.defineProperty(navigator, 'languages', {get: () => ['es-ES', 'es', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
    window.chrome = {runtime: {}};
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
            ? Promise.resolve({state: Notification.permission})
            : originalQuery(parameters)
    );
    delete navigator.__proto__.webdriver;
})();
"""

def log(msg: str) -> None:
    print(f"[BOT] {msg}", flush=True)

def notify_text(message: str) -> None:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=15,
        )
        log("✓ Telegram OK")
    except Exception as e:
        log(f"✗ Telegram: {e}")

def notify_with_photo(message: str, photo_path: str) -> None:
    if not TELEGRAM_TOKEN or not CHAT_ID or not Path(photo_path).exists():
        notify_text(message)
        return
    try:
        with open(photo_path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "caption": message, "parse_mode": "Markdown"},
                files={"photo": f},
                timeout=30,
            )
        log("✓ Foto OK")
    except Exception as e:
        log(f"✗ Foto: {e}")
        notify_text(message)

def read_state() -> str:
    return STATE_FILE.read_text().strip() if STATE_FILE.exists() else "unknown"

def write_state(value: str) -> None:
    STATE_FILE.write_text(value)

async def click_button(page) -> bool:
    selectors = [
        "text=Continue / Continuar",
        "text=Continuar",
        "button:has-text('Continuar')",
        "a:has-text('Continuar')",
    ]
    for sel in selectors:
        try:
            await page.locator(sel).first.click(timeout=5000)
            log(f"✓ Click Continue")
            return True
        except:
            pass
    return False

async def check_availability_attempt(attempt: int) -> tuple[str, str, str]:
    log(f"\n--- Intento {attempt + 1} ---")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        
        context = await browser.new_context(
            locale="es-ES",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "DNT": "1",
            },
            ignore_https_errors=True,
        )
        
        await context.add_init_script(STEALTH_JS)
        page = await context.new_page()

        try:
            log(f"🌐 Navegando...")
            await asyncio.sleep(random.uniform(3, 6))
            await page.goto(WIDGET_URL, wait_until="domcontentloaded", timeout=60000)
            log("✓ DOM loaded")

            log("⏳ Cloudflare (50s)...")
            await asyncio.sleep(50)

            await page.screenshot(path="step1_after_load.png", full_page=True)

            log("🔘 Click Continue...")
            await click_button(page)
            await asyncio.sleep(random.uniform(2, 4))

            log("⏳ Widget (90s)...")
            try:
                await page.wait_for_load_state("networkidle", timeout=60000)
            except:
                pass
            
            await asyncio.sleep(90)

            await page.screenshot(path="step2_final.png", full_page=True)

            # CONTENIDO PRINCIPAL
            full_content = await page.content()
            log(f"✓ HTML: {len(full_content)} chars")

            # IFRAMES (IMPORTANTE!)
            log(f"🔍 Frames: {len(page.frames)}")
            for i, frame in enumerate(page.frames):
                try:
                    frame_content = await frame.content()
                    log(f"  Frame {i}: {len(frame_content)} chars")
                    full_content += f"\n\n--- FRAME {i} ---\n" + frame_content
                except Exception as e:
                    log(f"  Frame {i}: error")

            # ANÁLISIS
            widget_loaded = any(m in full_content for m in WIDGET_LOADED_MARKERS)
            no_disponible = any(m in full_content for m in NO_AVAILABILITY_MARKERS)
            cloudflare_blocking = any(m in full_content for m in CLOUDFLARE_MARKERS)

            log(f"📊 Widget: {widget_loaded} | Citas: {no_disponible} | CF: {cloudflare_blocking}")

            if not widget_loaded:
                estado = "blocked" if cloudflare_blocking else "unknown"
            else:
                estado = "unavailable" if no_disponible else "available"

            return estado, full_content, "step2_final.png"

        finally:
            await browser.close()

async def check_availability() -> tuple[str, str, str]:
    for attempt in range(3):
        try:
            return await check_availability_attempt(attempt)
        except Exception as e:
            log(f"❌ Fallo: {e}")
            if attempt < 2:
                await asyncio.sleep(random.uniform(5, 10))
            else:
                raise

async def main() -> int:
    try:
        estado, content, screenshot = await check_availability()
    except Exception as e:
        err = f"⚠️ *Error*\n\n`{str(e)[:100]}`"
        log(err)
        if read_state() != "error":
            notify_text(err)
            write_state("error")
        return 1

    prev = read_state()
    log(f"\n📋 {prev} → {estado}\n")

    if estado == "available":
        if prev != "available":
            msg = f"🎉 *¡CITAS DISPONIBLES!*\n\n👉 [Reservar]({WIDGET_URL})"
            notify_with_photo(msg, screenshot)
        write_state("available")
    elif estado == "unavailable":
        write_state("unavailable")
    elif estado == "blocked":
        log("(Sin cambios)")

    Path("last_run.html").write_text(content[:300_000])
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
