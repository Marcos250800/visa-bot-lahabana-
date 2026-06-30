"""
Monitor FINAL v9 - Buscar botón en iframes
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

WIDGET_MARKERS = ["bookitit", "Cancelar o consultar"]
NO_CITAS = ["No hay horas disponibles", "Inténtelo de nuevo"]
CF_MARKERS = ["challenges.cloudflare.com", "Just a moment"]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'vendor', {get: () => 'Google Inc.'});
window.chrome = {runtime: {}};
"""

def log(msg: str) -> None:
    print(f"[BOT] {msg}", flush=True)

def notify(msg: str, photo: str = None) -> None:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    try:
        if photo and Path(photo).exists():
            with open(photo, "rb") as f:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                    data={"chat_id": CHAT_ID, "caption": msg, "parse_mode": "Markdown"},
                    files={"photo": f},
                    timeout=30,
                )
        else:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"},
                timeout=15,
            )
        log("✓ Telegram")
    except Exception as e:
        log(f"✗ Telegram: {e}")

def read_state() -> str:
    return STATE_FILE.read_text().strip() if STATE_FILE.exists() else "unknown"

def write_state(value: str) -> None:
    STATE_FILE.write_text(value)

async def check() -> tuple[str, str, str]:
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ])
        
        c = await b.new_context(
            locale="es-ES",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Accept-Language": "es-ES,es;q=0.9"},
            ignore_https_errors=True,
        )
        
        await c.add_init_script(STEALTH)
        page = await c.new_page()

        try:
            log("🌐 Navegando...")
            await asyncio.sleep(3)
            await page.goto(WIDGET_URL, wait_until="domcontentloaded", timeout=60000)
            log("✓ DOM loaded")

            log("⏳ Cloudflare (70s)...")
            for i in range(7):
                await asyncio.sleep(10)
                log(f"  {(i+1)*10}s")

            await page.screenshot(path="step1_after_load.png", full_page=True)

            # CLICK BOTÓN - BUSCAR EN IFRAMES
            log("🔘 Buscando botón...")
            clicked = False
            
            # Frame principal
            try:
                btn = page.locator("#idCaptchaButton")
                await btn.wait_for(state="visible", timeout=5000)
                await asyncio.sleep(random.uniform(2, 4))
                await btn.click()
                log("✓ Click OK (frame principal)")
                clicked = True
            except:
                log("  No en frame principal")
            
            # Iframes
            if not clicked:
                for i, frame in enumerate(page.frames):
                    try:
                        btn = frame.locator("#idCaptchaButton")
                        await btn.wait_for(state="visible", timeout=5000)
                        await asyncio.sleep(random.uniform(2, 4))
                        await btn.click()
                        log(f"✓ Click OK (Frame {i})")
                        clicked = True
                        break
                    except:
                        pass
            
            if not clicked:
                log("⚠️ Botón no encontrado")

            await asyncio.sleep(5)

            log("⏳ Widget (90s)...")
            try:
                await page.wait_for_load_state("networkidle", timeout=80000)
            except:
                pass
            
            for i in range(9):
                await asyncio.sleep(10)
                log(f"  {(i+1)*10}s")

            await page.screenshot(path="step2_final.png", full_page=True)

            html = await page.content()
            log(f"✓ HTML: {len(html)} chars")
            
            for i, frame in enumerate(page.frames):
                try:
                    fhtml = await frame.content()
                    log(f"  Frame {i}: {len(fhtml)} chars")
                    html += f"\n\n--- FRAME {i} ---\n{fhtml}"
                except:
                    pass

            has_widget = any(m in html for m in WIDGET_MARKERS)
            has_no_citas = any(m in html for m in NO_CITAS)
            has_cf = any(m in html for m in CF_MARKERS)

            log(f"📊 Widget: {has_widget} | Citas: {has_no_citas} | CF: {has_cf}")

            if not has_widget:
                estado = "blocked" if has_cf else "unknown"
            else:
                estado = "unavailable" if has_no_citas else "available"

            return estado, html, "step2_final.png"

        finally:
            await b.close()

async def main() -> int:
    try:
        estado, html, shot = await check()
    except Exception as e:
        log(f"❌ {e}")
        traceback.print_exc()
        if read_state() != "error":
            notify(f"⚠️ Error: {str(e)[:80]}")
            write_state("error")
        return 1

    prev = read_state()
    log(f"📋 {prev} → {estado}")

    if estado == "available":
        if prev != "available":
            notify(f"🎉 *¡CITAS DISPONIBLES!*\n\n👉 [Reservar]({WIDGET_URL})", shot)
        write_state("available")
    elif estado == "unavailable":
        write_state("unavailable")

    Path("last_run.html").write_text(html[:300_000])
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
