"""
Monitor de citas — Consulado de España en La Habana
Visado de residencia de familiares de españoles

Versión 3:
- Detección POSITIVA: solo notifica si el widget Bookitit cargó de verdad
- Stealth: scripts anti-detección para superar Cloudflare
- Envía screenshot con la notificación
- No genera falsos positivos cuando Cloudflare bloquea
"""

import asyncio
import os
import sys
import traceback
from pathlib import Path

import requests
from playwright.async_api import async_playwright

# --- Config ---
WIDGET_URL = (
    "https://www.citaconsular.es/es/hosteds/widgetdefault/"
    "2686d3b68dc9e0db0ba3c6a20437e9cc7"
)
PUBLIC_URL = (
    "https://www.exteriores.gob.es/Consulados/lahabana/es/ServiciosConsulares/"
    "Paginas/index.aspx?scco=Cuba&scd=166&scca=Visados"
    "&scs=Visados+Nacionales+-+Visado+de+residencia+de+familiares"
    "+de+personas+de+nacionalidad+espa%c3%b1ola"
)
STATE_FILE = Path("state.txt")

# Marcadores de que LLEGAMOS al widget de Bookitit (no nos bloqueó Cloudflare)
WIDGET_LOADED_MARKERS = [
    "bookitit",
    "Bookitit",
    "Consulado General de España",
    "Cancelar o consultar mis reservas",
]

# Marcadores de "no hay citas"
NO_AVAILABILITY_MARKERS = [
    "No hay horas disponibles",
    "no hay horas disponibles",
    "Inténtelo de nuevo dentro de unos días",
]

# Si vemos esto, Cloudflare nos bloqueó
CLOUDFLARE_MARKERS = [
    "challenges.cloudflare.com",
    "cf-challenge",
    "Verifying you are human",
    "Just a moment",
]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

# Script de stealth — elimina la huella de "automatización" que Cloudflare detecta
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['es-ES', 'es', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
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


# --- Telegram ---
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
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        r.raise_for_status()
        log("Mensaje texto enviado a Telegram")
    except Exception as e:
        log(f"Error enviando texto a Telegram: {e}")


def notify_with_photo(message: str, photo_path: str) -> None:
    """Envía mensaje con foto adjunta a Telegram."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        log("Falta TELEGRAM_TOKEN o CHAT_ID")
        return
    if not Path(photo_path).exists():
        log(f"No existe foto {photo_path}, mando solo texto")
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
        log("Mensaje con foto enviado a Telegram")
    except Exception as e:
        log(f"Error enviando foto a Telegram: {e}, intento solo texto")
        notify_text(message)


# --- Estado ---
def read_state() -> str:
    if STATE_FILE.exists():
        return STATE_FILE.read_text().strip()
    return "unknown"


def write_state(value: str) -> None:
    STATE_FILE.write_text(value)


# --- Scraping ---
async def click_continue(page) -> bool:
    selectors = [
        "text=Continue / Continuar",
        "text=Continuar",
        "text=Continue",
        "button:has-text('Continuar')",
        "button:has-text('Continue')",
        "a:has-text('Continuar')",
        "a:has-text('Continue')",
        "input[type='submit'][value*='ontinu']",
        "[onclick*='continu' i]",
    ]
    for sel in selectors:
        try:
            log(f"  Probando selector: {sel}")
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=8000)
            await loc.click()
            log(f"  Click hecho con: {sel}")
            return True
        except Exception:
            continue
    return False


async def check_availability() -> tuple[str, str, str]:
    """Devuelve (estado, contenido_html, ruta_screenshot).
    Estado: 'available' | 'unavailable' | 'blocked' | 'unknown'
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        context = await browser.new_context(
            locale="es-ES",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            extra_http_headers={
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            },
        )
        # Inyectar stealth en todas las páginas/frames
        await context.add_init_script(STEALTH_JS)

        page = await context.new_page()

        async def handle_dialog(dialog):
            log(f"  Dialog detectado: {dialog.message[:80]}")
            await dialog.accept()

        page.on("dialog", lambda d: asyncio.create_task(handle_dialog(d)))

        try:
            log(f"Navegando a: {WIDGET_URL}")
            await page.goto(WIDGET_URL, wait_until="domcontentloaded", timeout=45000)
            log("DOM cargado")

            # Espera generosa para que Cloudflare resuelva (a veces lo hace solo)
            await asyncio.sleep(8)

            await page.screenshot(path="step1_after_load.png", full_page=True)
            log("Screenshot: step1_after_load.png")

            log("Buscando botón Continue...")
            clicked = await click_continue(page)

            if not clicked:
                log("No se encontró Continue")
                Path("debug_no_button.html").write_text(await page.content())

            log("Esperando render del widget...")
            try:
                await page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                log("networkidle no llegó")

            # Espera larga adicional para Bookitit
            await asyncio.sleep(10)

            await page.screenshot(path="step2_final.png", full_page=True)
            log("Screenshot: step2_final.png")

            # Recolectar todo el contenido
            full_content = await page.content()
            log(f"HTML principal: {len(full_content)} chars")

            for i, frame in enumerate(page.frames):
                try:
                    frame_html = await frame.content()
                    log(f"  Frame {i}: {frame.url[:80]} — {len(frame_html)} chars")
                    full_content += f"\n\n--- FRAME {i}: {frame.url} ---\n\n" + frame_html
                except Exception as e:
                    log(f"  Frame {i} no accesible: {e}")

            # --- LÓGICA DE DETECCIÓN ---
            widget_loaded = any(m in full_content for m in WIDGET_LOADED_MARKERS)
            no_disponible = any(m in full_content for m in NO_AVAILABILITY_MARKERS)
            cloudflare_blocking = any(m in full_content for m in CLOUDFLARE_MARKERS)

            log(f"¿Widget Bookitit cargado?  {widget_loaded}")
            log(f"¿'No hay horas' presente?   {no_disponible}")
            log(f"¿Cloudflare bloqueando?    {cloudflare_blocking}")

            if not widget_loaded:
                if cloudflare_blocking:
                    estado = "blocked"
                else:
                    estado = "unknown"
            else:
                if no_disponible:
                    estado = "unavailable"
                else:
                    estado = "available"

            return estado, full_content, "step2_final.png"

        finally:
            await browser.close()


async def main() -> int:
    try:
        estado, content, screenshot = await check_availability()
    except Exception as e:
        err = f"⚠️ *Error en bot de citas*\n\n`{type(e).__name__}: {e}`"
        log(err)
        traceback.print_exc()
        if read_state() != "error":
            notify_text(err)
            write_state("error")
        return 1

    prev = read_state()
    log(f"Estado anterior: {prev} | Estado actual: {estado}")

    if estado == "available":
        if prev != "available":
            msg = (
                "🎉 *¡HAY CITAS DISPONIBLES!*\n\n"
                "Consulado de España en La Habana\n"
                "_Visado de residencia de familiares de españoles_\n\n"
                f"👉 [Reservar ahora]({WIDGET_URL})\n\n"
                f"ℹ️ [Página oficial]({PUBLIC_URL})\n\n"
                "⚡ Ve YA — vuelan en minutos."
            )
            notify_with_photo(msg, screenshot)
        else:
            log("Siguen abiertas, no renotifico")
        write_state("available")

    elif estado == "unavailable":
        if prev == "available":
            log("Se cerró la ventana de disponibilidad")
        log("Sin citas — no notifico")
        write_state("unavailable")

    elif estado == "blocked":
        log("Cloudflare nos bloqueó este run. No notifico ni cambio estado.")
        # NO cambiamos state.txt — no queremos perder el estado real

    else:  # unknown
        log("Estado desconocido — no notifico ni cambio estado.")

    # Guardar HTML siempre para depurar
    Path("last_run.html").write_text(content[:300_000])
    return 0

if __name__ == "__main__":
       sys.exit(asyncio.run(main()))
