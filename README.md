# Bot Citas — Consulado España La Habana

Monitorea cada 5 min la disponibilidad de citas para **Visado de residencia de familiares de españoles** y avisa por Telegram cuando aparece hueco.

## Cómo funciona

1. GitHub Actions corre `monitor.py` cada 5 min (cron).
2. El script abre el widget de Bookitit con Playwright, acepta el diálogo y pulsa "Continue".
3. Lee el HTML (incluidos iframes) y busca el texto `No hay horas disponibles`.
4. Si **antes** no había y **ahora sí**, manda mensaje a Telegram.
5. Guarda el estado en `state.txt` y lo commitea — así no spamea cuando ya avisó.

## Setup inicial (una vez)

### 1. Crear el repo

```bash
cd visa-bot
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin git@github.com:Marcos250800/visa-bot-lahabana.git
git push -u origin main
```

### 2. Obtener el `CHAT_ID` de Telegram

Con el bot ya creado en @BotFather:

1. Abre tu bot en Telegram y mándale cualquier mensaje (ej. `/start`).
2. Visita en el navegador:
   ```
   https://api.telegram.org/bot<TU_TOKEN>/getUpdates
   ```
3. Busca `"chat":{"id":XXXXXXXX,...}` — ese número es tu `CHAT_ID`.

Si quieres avisar a un **grupo**, añade el bot al grupo, manda un mensaje, y el `chat.id` será un número negativo (ej. `-1001234567890`).

### 3. Configurar secrets en GitHub

En el repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Nombre | Valor |
|---|---|
| `TELEGRAM_TOKEN` | El token nuevo de @BotFather (el viejo ya está quemado) |
| `CHAT_ID` | El número del paso anterior |

### 4. Activar Actions

Settings → Actions → General → "Allow all actions and reusable workflows" → Save.

Y en Workflow permissions: **Read and write permissions** (para que pueda commitear `state.txt`).

### 5. Probar manualmente

Actions → "Check Visa Appointments" → **Run workflow**. Mira los logs.

## Aumentar fiabilidad con cron-job.org (opcional pero recomendado)

El cron de GitHub Actions tiene latencia variable (5-20 min en horas pico). Para forzar ejecución puntual:

1. Crea un **Personal Access Token (classic)** con scope `repo` y `workflow`.
2. En cron-job.org, configura un job cada 5 min con:
   - **URL:** `https://api.github.com/repos/Marcos250800/visa-bot-lahabana/actions/workflows/check.yml/dispatches`
   - **Method:** POST
   - **Headers:**
     - `Authorization: Bearer <TU_PAT>`
     - `Accept: application/vnd.github+json`
     - `Content-Type: application/json`
   - **Body:** `{"ref":"main"}`

## Depurar

- Si falla, el workflow sube `last_run.html` como artifact (3 días). Descárgalo y abre en el navegador para ver qué cargó Playwright.
- Si Bookitit cambia el texto o el botón, ajusta:
  - `NO_AVAILABILITY_MARKERS` en `monitor.py`
  - El selector `text=Continue / Continuar`

## Archivos

```
monitor.py              # script principal
requirements.txt        # deps
state.txt               # estado (lo crea solo)
.github/workflows/
  check.yml             # cron de Actions
```
