"""
Monitor de citas — Consulado de España en La Habana
Visado de residencia de familiares de españoles

Flujo:
1. Abrir el widget de citaconsular.es (Bookitit)
2. Aceptar el dialog "Welcome / Bienvenido"
3. Click en "Continue / Continuar"
4. Leer si sale "No hay horas disponibles" o el calendario
5. Notificar por Telegram solo cuando cambia de "sin citas" a "con citas"
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


# --- Telegram ---
def notify(message: str) -> None:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️  Falta TELEGRAM_TOKEN o CHAT_ID — no se envía notificación")
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
    except Exception as e:
        print(f"❌ Error enviando a Telegram: {e}")


# --- Estado ---
def read_state() -> str:
    if STATE_FILE.exists():
        return STATE_FILE.read_text().strip()
    return "unknown"


def write_state(value: str) -> None:
    STATE_FILE.write_text(value)


# --- Scraping ---
async def check_availability() -> tuple[bool, str]:
    """Devuelve (hay_disponibilidad, contenido_completo_para_debug)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
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

        # Auto-aceptar el native dialog "Welcome / Bienvenido"
        page.on("dialog", lambda d: asyncio.create_task(d.accept()))

        try:
            await page.goto(WIDGET_URL, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2)

            # Click en "Continue / Continuar"
            continue_btn = page.locator("text=Continue / Continuar").first
            try:
                await continue_btn.wait_for(state="visible", timeout=20000)
                await continue_btn.click()
            except Exception:
                # Fallback: buscar por role
                await page.get_by_role("button", name=lambda n: "Continu" in (n or "")).click()

            # Esperar a que cargue el widget (iframe de Bookitit)
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(5)

            # Recopilar contenido del documento principal + todos los iframes
            full_content = await page.content()
            for frame in page.frames:
                try:
                    frame_html = await frame.content()
                    full_content += "\n\n--- FRAME ---\n\n" + frame_html
                except Exception:
                    pass

            no_disponible = any(
                marker in full_content for marker in NO_AVAILABILITY_MARKERS
            )
            return (not no_disponible), full_content

        finally:
            await browser.close()


# --- Main ---
async def main() -> int:
    try:
        available, content = await check_availability()
    except Exception as e:
        err = f"⚠️ *Error en bot de citas*\n\n`{type(e).__name__}: {e}`"
        print(err)
        traceback.print_exc()
        # Solo notificar errores nuevos (no en cada run si el sitio cae)
        if read_state() != "error":
            notify(err)
            write_state("error")
        return 1

    prev = read_state()
    current = "available" if available else "unavailable"

    print(f"Estado anterior: {prev} | Estado actual: {current}")

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
            print("Siguen abiertas — no renotifico.")
    else:
        if prev == "available":
            print("Se cerró la ventana de disponibilidad.")
        # No notifico cuando NO hay citas; sería spam.

    write_state(current)

    # Guardar un dump del HTML por si hay que depurar selectores
    Path("last_run.html").write_text(content[:200_000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
