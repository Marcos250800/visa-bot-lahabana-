"""
Monitor de citas — Consulado de España en La Habana
Visado de residencia de familiares de españoles

Versión 5 - CLOUDFLARE BYPASS PROFESIONAL:
- cloudscraper para bypass de Cloudflare
- Session management con cookies reales
- Delays humanos y rotación de user-agents
- Detección positiva solo con widget cargado
"""

import asyncio
import os
import sys
import traceback
import random
import time
from pathlib import Path
from urllib.parse import urljoin

import cloudscraper
import requests
from playwright.async_api import async_playwright

# --- Config ---
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
    "Enable JavaScript and cookies",
]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['es-ES', 'es', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'vendor', { get: () => 'Google Inc.' });
window.chrome = { runtime: {} };
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);
"""

def log(msg: str) -> None:
    print(f"[BOT] {msg}", flush=True)

def notify_text(message: str) -> None:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        log("Falta TELEGRAM_TOKEN o CHAT_ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
            },
            timeout=15,
        )
        r.raise_for_status()
        log("✓ Mensaje enviado a Telegram")
    except Exception as e:
        log(f"✗ Error Telegram: {e}")

def notify_with_photo(message: str, photo_path: str) -> None:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        log("Falta TELEGRAM_TOKEN o CHAT_ID")
        return
    if not Path(photo_path).exists():
        notify_text(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            r = requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "caption": message,
                    "parse_mode": "Markdown",
                },
                files={"photo": f},
                timeout=30,
            )
        r.raise_for_status()
        log("✓ Foto enviada a Telegram")
    except Exception as e:
        log(f"✗ Error foto: {e}")
        notify_text(message)

def read_state() -> str:
    if STATE_FILE.exists():
        return STATE_FILE.read_text().strip()
    return "unknown"

def write_state(value: str) -> None:
    STATE_FILE.write_text(value)

async def click_continue(page) -> bool:
    selectors = [
        "text=Continue / Continuar",
        "text=Continuar",
        "button:has-text('Continuar')",
        "a:has-text('Continuar')",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=5000)
            await asyncio.sleep(random.uniform(1, 2))
            await loc.click()
            log(f"✓ Click en Continue")
            return True
        except Exception:
            continue
    return False

async def check_availability() -> tuple[str, str, str]:
    """Pre-fetch con cloudscraper + Playwright con sesión"""
    
    # PASO 1: Usar cloudscraper para obtener cookies de Cloudflare
    log("🔓 Obteniendo bypass de Cloudflare con cloudscraper...")
    try:
        scraper = cloudscraper.create_scraper()
        scraper.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "es-ES,es;q=0.9",
        })
        
        await asyncio.sleep(random.uniform(1, 3))
        response = scraper.get(WIDGET_URL, timeout=30)
        log(f"✓ Response status: {response.status_code}")
        
        # Extraer cookies
        cf_cookies = scraper.cookies
        log(f"✓ Cookies obtenidas: {len(cf_cookies)} cookies")
        
    except Exception as e:
        log(f"⚠️ cloudscraper falló: {e}, continuando con playwright...")
        cf_cookies = {}

    # PASO 2: Usar Playwright con las cookies
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
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "DNT": "1",
            },
            ignore_https_errors=True,
        )

        # Agregar cookies de Cloudflare si existen
        if cf_cookies:
            for cookie in cf_cookies:
                try:
                    context.add_cookies([{
                        "name": cookie.name,
                        "value": cookie.value,
                        "domain": cookie.domain or "citaconsular.es",
                        "path": cookie.path or "/",
                    }])
                except Exception:
                    pass

        await context.add_init_script(STEALTH_JS)
        page = await context.new_page()

        try:
            log(f"🌐 Navegando a widget...")
            await asyncio.sleep(random.uniform(2, 4))
            
            await page.goto(WIDGET_URL, wait_until="domcontentloaded", timeout=60000)
            log(f"✓ Página cargada")

            # Espera larga para Cloudflare
            log(f"⏳ Esperando Cloudflare (30s)...")
            await asyncio.sleep(30)

            await page.screenshot(path="step1_after_load.png", full_page=True)

            # Click Continue
            log(f"🔘 Buscando botón...")
            await click_continue(page)

            log(f"⏳ Esperando widget Bookitit (30s)...")
            try:
                await page.wait_for_load_state("networkidle", timeout=40000)
            except:
                pass

            await asyncio.sleep(30)
            await page.screenshot(path="step2_final.png", full_page=True)

            # Recolectar contenido
            full_content = await page.content()
            log(f"✓ HTML: {len(full_content)} chars")

            for i, frame in enumerate(page.frames):
                try:
                    frame_html = await frame.content()
                    log(f"  Frame {i}: {len(frame_html)} chars")
                    full_content += f"\n\n--- FRAME {i} ---\n\n" + frame_html
                except:
                    pass

            # LÓGICA DE DETECCIÓN
            widget_loaded = any(m in full_content for m in WIDGET_LOADED_MARKERS)
            no_disponible = any(m in full_content for m in NO_AVAILABILITY_MARKERS)
            cloudflare_blocking = any(m in full_content for m in CLOUDFLARE_MARKERS)

            log(f"📊 Widget cargado: {widget_loaded}")
            log(f"📊 Sin citas: {no_disponible}")
            log(f"📊 Cloudflare bloquea: {cloudflare_blocking}")

            if not widget_loaded:
                estado = "blocked" if cloudflare_blocking else "unknown"
            else:
                estado = "unavailable" if no_disponible else "available"

            return estado, full_content, "step2_final.png"

        finally:
            await browser.close()

async def main() -> int:
    try:
        estado, content, screenshot = await check_availability()
    except Exception as e:
        err = f"⚠️ *Error en bot*\n\n`{type(e).__name__}: {e}`"
        log(err)
        traceback.print_exc()
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
                "Consulado: La Habana\n"
                "Visado: Residencia (familiares)\n\n"
                f"👉 [RESERVAR AHORA]({WIDGET_URL})\n"
                f"📄 [Más info]({PUBLIC_URL})"
            )
            notify_with_photo(msg, screenshot)
        write_state("available")

    elif estado == "unavailable":
        if prev == "available":
            log("Se cerró disponibilidad")
        write_state("unavailable")

    elif estado == "blocked":
        log("Cloudflare bloqueó - sin cambiar estado")

    Path("last_run.html").write_text(content[:300_000])
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
