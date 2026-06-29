"""
Monitor de citas — Consulado de España en La Habana
Visado de residencia de familiares de españoles

Versión 2 — más robusta:
- Múltiples selectores para el botón Continue
- Esperas más largas
- Screenshot + HTML siempre, no solo en fallo
- Logging detallado
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
NO_AVAILABILITY_MARKERS = [
    "No hay horas disponibles",
    "no hay horas disponibles",
    "Inténtelo de nuevo dentro de unos días",
]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()


def log(msg: str) -> None:
    print(f"[BOT] {msg}", flush=True)


# --- Telegram ---
def notify(message: str) -> None:
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
        log("Mensaje enviado a Telegram")
    except Exception as e:
        log(f"Error enviando a Telegram: {e}")


# --- Estado ---
def read_state() -> str:
    if STATE_FILE.exists():
        return STATE_FILE.read_text().strip()
    return "unknown"


def write_state(value: str) -> None:
    STATE_FILE.write_text(value)


# --- Scraping ---
async def click_continue(page) -> bool:
    """Intenta clickear el botón Continue con varios selectores."""
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


async def check_availability() -> tuple[bool, str]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
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
        )
        page = await context.new_page()

        async def handle_dialog(dialog):
            log(f"  Dialog detectado: {dialog.message[:80]}")
            await dialog.accept()

        page.on("dialog", lambda d: asyncio.create_task(handle_dialog(d)))

        try:
            log(f"Navegando a: {WIDGET_URL}")
            await page.goto(WIDGET_URL, wait_until="domcontentloaded", timeout=45000)
            log("DOM cargado")

            await asyncio.sleep(5)

            await page.screenshot(path="step1_after_load.png", full_page=True)
            log("Screenshot: step1_after_load.png")

            log("Buscando botón Continue...")
            clicked = await click_continue(page)

            if not clicked:
                log("No se encontró Continue, sigo de todos modos")
                Path("debug_no_button.html").write_text(await page.content())

            log("Esperando render del widget...")
            try:
                await page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                log("networkidle no llegó")

            await asyncio.sleep(7)

            await page.screenshot(path="step2_final.png", full_page=True)
            log("Screenshot: step2_final.png")

            full_content = await page.content()
            log(f"HTML principal: {len(full_content)} chars")

            for i, frame in enumerate(page.frames):
                try:
                    frame_html = await frame.content()
                    log(f"  Frame {i}: {frame.url[:60]} — {len(frame_html)} chars")
                    full_content += f"\n\n--- FRAME {i}: {frame.url} ---\n\n" + frame_html
                except Exception as e:
                    log(f"  Frame {i} no accesible: {e}")

            no_disponible = any(m in full_content for m in NO_AVAILABILITY_MARKERS)
            log(f"'No hay horas disponibles' encontrado: {no_disponible}")

            return (not no_disponible), full_content

        finally:
            await browser.close()


async def main() -> int:
    try:
        available, content = await check_availability()
    except Exception as e:
        err = f"⚠️ *Error en bot de citas*\n\n`{type(e).__name__}: {e}`"
        log(err)
        traceback.print_exc()
        if read_state() != "error":
            notify(err)
            write_state("error")
        return 1

    prev = read_state()
    current = "available" if available else "unavailable"

    log(f"Estado anterior: {prev} | Estado actual: {current}")

    if available:
        if prev != "available":
            msg = (
                "🎉 *¡HAY CITAS DISPONIBLES!*\n\n"
                "Consulado de España en La Habana\n"
                "_Visado de residencia de familiares de españoles_\n\n"
                f"👉 [Reservar ahora]({WIDGET_URL})\n\n"
                f"ℹ️ [Página oficial]({PUBLIC_URL})\n\n"
                "⚡ Ve YA — vuelan en minutos."
            )
            notify(msg)
        else:
            log("Siguen abiertas, no renotifico")
    else:
        log("Sin citas — no notifico")

    write_state(current)
    Path("last_run.html").write_text(content[:300_000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
