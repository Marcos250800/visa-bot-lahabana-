"""
Monitor FINAL v12 - Usar ID directo para botón Continue + buscar en iframes
"""

import asyncio
import os
import sys
import traceback
import random
from pathlib import Path

import requests
from playwright.async_api import async_playwright

# URL PÚBLICA - Punto de entrada
PUBLIC_URL = "https://www.exteriores.gob.es/Consulados/lahabana/es/ServiciosConsulares/Paginas/index.aspx?scco=Cuba&scd=166&scca=Visados&scs=Visados+Nacionales+-+Visado+de+residencia+de+familiares+de+personas+de+nacionalidad+espa%c3%b1ola"

# URL del widget (para mostrar después)
WIDGET_URL = "https://www.citaconsular.es/es/hosteds/widgetdefault/2686d3b68dc9e0ba3c6a20437e9cc7"
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
        
        # Manejar automáticamente cualquier alerta nativa (como el "Welcome / Bienvenido")
        c.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        
        await c.add_init_script(STEALTH)
        page = await c.new_page()

        try:
            # ========== PASO 1: ENTRAR A LA URL PÚBLICA ==========
            log("🌐 PASO 1: Navegando a página pública...")
            await asyncio.sleep(2)
            await page.goto(PUBLIC_URL, wait_until="domcontentloaded", timeout=60000)
            log("✓ Página pública cargada")
            await page.screenshot(path="step1_public_page.png", full_page=True)
            
            await asyncio.sleep(3)

            # ========== PASO 2: BUSCAR Y CLICKEAR ENLACE "Reservar cita de visados RFX" ==========
            log("🔘 PASO 2: Buscando enlace para abrir widget...")
            
            link_selectors = [
                "a:has-text('Reservar cita de visados RFX')",
                "a[href*='citaconsular']",
                "a:has-text('Reservar')",
            ]
            
            link_clicked = False
            for selector in link_selectors:
                try:
                    log(f"  Intentando selector: {selector}")
                    link = page.locator(selector)
                    await link.first.wait_for(state="visible", timeout=5000)
                    await asyncio.sleep(random.uniform(1, 2))
                    await link.first.click()
                    log("✓ Click en enlace de reserva")
                    
                    # IMPORTANTE: Muchos sitios de consulados abren el widget en una NUEVA pestaña (target="_blank")
                    # Damos un pequeño margen para que se abra la pestaña
                    await asyncio.sleep(4)
                    if len(c.pages) > 1:
                        page = c.pages[-1] # Tomamos la última pestaña abierta
                        await page.bring_to_front()
                        log("✓ Cambiado a la nueva pestaña abierta")
                    else:
                        log("✓ Seguimos en la misma pestaña")
                        
                    link_clicked = True
                    break
                except Exception as e:
                    log(f"  ✗ No encontrado: {type(e).__name__}")
            
            if not link_clicked:
                log("⚠️ Enlace no encontrado, continuando...")
            
            await asyncio.sleep(5)

            # ========== PASO 3: CLICK EN BOTÓN "ACEPTAR" (Modal HTML si lo hay) ==========
            log("🔘 PASO 3: Buscando botón ACEPTAR (interno)...")
            await page.screenshot(path="step2_before_aceptar.png", full_page=True)
            
            aceptar_clicked = False
            aceptar_selectors = [
                "button:has-text('Aceptar')",
                "[onclick*='Aceptar']",
                "button[aria-label*='Aceptar']",
            ]
            
            for selector in aceptar_selectors:
                try:
                    btn = page.locator(selector)
                    await btn.first.wait_for(state="visible", timeout=2000)
                    await btn.first.click()
                    log("✓ Click en ACEPTAR (frame principal)")
                    aceptar_clicked = True
                    break
                except:
                    pass
            
            if not aceptar_clicked:
                for i, frame in enumerate(page.frames):
                    for selector in aceptar_selectors:
                        try:
                            btn = frame.locator(selector)
                            await btn.first.wait_for(state="visible", timeout=2000)
                            await btn.first.click()
                            log(f"✓ Click en ACEPTAR (Frame {i})")
                            aceptar_clicked = True
                            break
                        except:
                            pass
                    if aceptar_clicked:
                        break
            
            if not aceptar_clicked:
                log("  (No hay botón ACEPTAR en el código, esto es NORMAL porque ya se aceptó la alerta de Welcome en fondo)")
            
            await asyncio.sleep(3)
            await page.screenshot(path="step3_after_aceptar.png", full_page=True)

            # ========== PASO 4: CLICK EN BOTÓN "CONTINUAR" (verde) ==========
            log("🔘 PASO 4: Esperando a que cargue la página y buscando botón CONTINUAR...")
            
            # Esperamos a que la red se calme por si hay Cloudflare u otro sistema cargando
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass
                
            await asyncio.sleep(3)
            
            continue_clicked = False
            continue_selectors = [
                "#idCaptchaButton",
                "button:has-text('Continuar')",
                "button:has-text('Continue')",
                "button.btn-success",
                "input[value='Continuar']",
                "a:has-text('Continuar')"
            ]
            
            # Buscar en frame principal
            for selector in continue_selectors:
                try:
                    log(f"  Frame principal - Intentando: {selector}")
                    btn = page.locator(selector)
                    await btn.first.wait_for(state="visible", timeout=3000)
                    await asyncio.sleep(random.uniform(1, 2))
                    await btn.first.click()
                    log(f"✓ Click en CONTINUAR exitoso (Frame principal)")
                    continue_clicked = True
                    break
                except:
                    pass
            
            # Buscar en iframes si no encontró
            if not continue_clicked:
                for i, frame in enumerate(page.frames):
                    for selector in continue_selectors:
                        try:
                            log(f"  Frame {i} - Intentando: {selector}")
                            btn = frame.locator(selector)
                            await btn.first.wait_for(state="visible", timeout=3000)
                            await asyncio.sleep(random.uniform(1, 2))
                            await btn.first.click()
                            log(f"✓ Click en CONTINUAR exitoso (Frame {i})")
                            continue_clicked = True
                            break
                        except:
                            pass
                    if continue_clicked:
                        break
            
            if not continue_clicked:
                log("⚠️ Error crítico: Botón CONTINUAR no encontrado en toda la página ni sus iframes.")

            await asyncio.sleep(5)

            # ========== PASO 5: ESPERAR A WIDGET Y ANALIZAR ==========
            log("⏳ PASO 5: Esperando widget (90s)...")
            try:
                await page.wait_for_load_state("networkidle", timeout=80000)
            except:
                pass
            
            for i in range(9):
                await asyncio.sleep(10)
                log(f"  {(i+1)*10}s")

            await page.screenshot(path="step4_final.png", full_page=True)

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

            log(f"📊 Widget: {has_widget} | Sin citas: {has_no_citas} | Cloudflare: {has_cf}")

            if not has_widget:
                estado = "blocked" if has_cf else "unknown"
            else:
                estado = "unavailable" if has_no_citas else "available"

            return estado, html, "step4_final.png"

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
