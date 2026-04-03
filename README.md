# 🏠 Scraper Inmobiliario Adaptativo

Web scraper que extrae, normaliza y envía datos de propiedades inmobiliarias desde múltiples sitios.
Combina un **núcleo Rust** de alto rendimiento con **Python asyncio** para la orquestación,
y un **motor de reglas Steel/Scheme** que se auto-extiende via LLM cuando encuentra datos desconocidos.

---

## Tabla de contenidos

- [Arquitectura](#arquitectura)
- [Stack tecnológico](#stack-tecnológico)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Requisitos previos](#requisitos-previos)
- [Instalación](#instalación)
- [Configuración (.env)](#configuración-env)
- [Esquema canónico](#esquema-canónico)
- [Motor de reglas](#motor-de-reglas)
- [Body mapping configurable](#body-mapping-configurable)
- [BrowserPool](#browserpool)
- [Pipeline de normalización](#pipeline-de-normalización)
- [Cliente LLM](#cliente-llm)
- [Cliente HTTP (monolito)](#cliente-http-monolito)
- [Tests](#tests)
- [Uso](#uso)
- [Decisiones de diseño](#decisiones-de-diseño)

---

## Arquitectura

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                        runner.py                                │
  │          run(sitios, paralelo=True, workers=4)                  │
  └──────────┬────────────────────┬─────────────────────┬──────────┘
             │                    │                     │
             ▼                    ▼                     ▼
  ┌──────────────────┐ ┌──────────────────┐  ┌──────────────────┐
  │   BrowserPool    │ │  normalizador.py │  │   cliente.py     │
  │ 1 browser        │ │                  │  │ POST httpx async │
  │ N contextos      │ │  ┌────────────┐  │  │ retry 3x backoff │
  │ via Semaphore    │ │  │ Extractor  │  │  └──────────────────┘
  └──────────────────┘ │  │   (Rust)   │  │
                       │  └────────────┘  │
                       │  ┌────────────┐  │
                       │  │MotorReglas │  │
                       │  │(Rust+Steel)│  │
                       │  └────────────┘  │
                       │  ┌────────────┐  │
                       │  │  LLM Groq  │  │
                       │  │ (fallback) │  │
                       │  └────────────┘  │
                       └──────────────────┘
```

**Flujo por propiedad:**

1. **BrowserPool** abre un contexto Chromium → navega a la URL → captura HTML
2. **Extractor** (Rust) parsea coordenadas de GMaps/Leaflet y normaliza precios
3. **MotorReglas** (Rust+Steel) evalúa reglas `.scm` que matchean la fuente
4. Si quedan **campos sin resolver**, el **LLM** genera nuevas reglas Scheme
5. Las reglas generadas se **persisten en disco** (auto-aprendizaje)
6. La propiedad normalizada se envía al **monolito** via POST httpx

---

## Stack tecnológico

| Componente | Tecnología | Propósito |
|---|---|---|
| Lenguaje principal | Python 3.11+ | Orquestación, async, schemas |
| Núcleo de extracción | Rust + PyO3 (maturin) | Parsing HTML, coords, precios — rendimiento nativo |
| Motor de reglas | Steel (Scheme embebido en Rust) | Reglas declarativas `.scm`, extensibles sin recompilar |
| Captura web | Playwright (Chromium headless) | Rendering JS, SPAs, iframes |
| Esquema de datos | Pydantic v2 | Validación estricta del esquema canónico |
| Configuración | pydantic-settings | Variables de entorno + `.env` |
| HTTP async | httpx | POST al monolito, sin bloquear el event loop |
| LLM | Groq (llama-3.3-70b-versatile) | Auto-generación de reglas para datos desconocidos |
| Scheduler | APScheduler | Ejecución cron sin procesos externos |
| Gestor de paquetes | uv | Rápido, lockfile determinista |

---

## Estructura del proyecto

```
scraper/
├── Cargo.toml              # Dependencias Rust
├── pyproject.toml           # Dependencias Python + build maturin
├── body_mapping.toml        # Mapping configurable Propiedad → body del monolito
├── .env.example             # Template de variables de entorno
├── .env                     # ⛔ (no se commitea) Variables reales
├── uv.lock                  # (generado) Lockfile determinista
│
├── src/                     # ── Código Rust ──
│   ├── lib.rs               # Entry point PyO3: expone MotorReglas y Extractor
│   ├── extractor.rs         # Parsing de coords (Leaflet/GMaps) y precios
│   └── motor.rs             # Steel embebido: carga y evalúa reglas .scm
│
├── scraper/                 # ── Código Python ──
│   ├── __init__.py          # Exports del paquete
│   ├── config.py            # Settings desde .env con pydantic-settings
│   ├── schema.py            # Esquema canónico Propiedad (Pydantic v2)
│   ├── pool.py              # BrowserPool: 1 browser, N contextos
│   ├── runner.py            # run() — entry point único de ejecución
│   ├── normalizador.py      # Pipeline: Extractor → MotorReglas → LLM
│   ├── llm.py               # Cliente Groq para inferir reglas Scheme
│   └── cliente.py           # POST httpx async al monolito
│
├── reglas/                  # ── Reglas Steel/Scheme ──
│   ├── reglas.toml          # Índice de reglas con metadata
│   ├── base/                # Reglas globales (aplican a cualquier fuente)
│   │   ├── leaflet.scm      # Extraer lat/lng de Leaflet
│   │   ├── gmaps.scm        # Extraer lat/lng de iframe Google Maps
│   │   └── precio.scm       # Normalizar precio_raw
│   └── sitios/              # Reglas por sitio (se pueblan en runtime via LLM)
│
└── tests/
    ├── __init__.py
    ├── fixtures/             # HTMLs estáticos para tests
    │   ├── gmaps_embed.html
    │   ├── gmaps_query.html
    │   └── leaflet.html
    └── test_motor.py         # 12 tests: coords, precios, schema
```

---

## Requisitos previos

| Requisito | Versión mínima | Cómo verificar |
|---|---|---|
| Python | 3.11+ | `python3 --version` |
| Rust | stable (cualquier reciente) | `rustc --version` |
| uv | 0.1+ | `uv --version` |

### Instalar Rust (si no lo tenés)

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

### Instalar uv (si no lo tenés)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Instalación

```bash
# 1. Clonar el repo
git clone <tu-repo-url> && cd scraper

# 2. Instalar dependencias Python (crea .venv automáticamente)
uv sync

# 3. Compilar la extensión Rust → genera scraper/_scraper_core.so
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 maturin develop --release

# 4. Instalar Chromium para Playwright
uv run playwright install chromium

# 5. Copiar y configurar variables de entorno
cp .env.example .env
# Editar .env con tus valores (ver sección siguiente)

# 6. Verificar que todo funciona
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 uv run pytest tests/ -v
```

> **Nota sobre `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1`:**
> PyO3 0.21 no declara soporte oficial para Python 3.13+, pero funciona
> perfectamente usando la ABI estable de Python. Este flag suprime el check de versión.

---

## Configuración (.env)

El scraper usa **pydantic-settings** para leer configuración.
Busca las variables en este orden de prioridad:

1. **Variables de entorno del sistema** (mayor prioridad)
2. **Archivo `.env`** en la raíz del proyecto
3. **Valores por defecto** del código

### Crear el archivo .env

```bash
cp .env.example .env
```

Luego editá `.env` con tus valores reales.

### Variables disponibles

| Variable | Tipo | Default | Obligatoria | Descripción |
|---|---|---|---|---|
| `GROQ_API_KEY` | `str` | `""` | **Sí** ¹ | API key de [Groq](https://console.groq.com/keys) para el LLM |
| `MONOLITO_URL` | `str` | `http://localhost:8000` | No | URL base del monolito receptor |
| `MAX_WORKERS` | `int` | `4` | No | Contextos de navegador concurrentes |
| `PARALELO` | `bool` | `true` | No | `true` = asyncio.gather / `false` = secuencial |
| `LOG_LEVEL` | `str` | `INFO` | No | Nivel de logging (DEBUG, INFO, WARNING, ERROR) |
| `REGLAS_PATH` | `str` | `reglas/reglas.toml` | No | Ruta al índice de reglas |
| `BODY_MAPPING_PATH` | `str` | `body_mapping.toml` | No | Ruta al archivo de mapping Propiedad → body POST |

> ¹ `GROQ_API_KEY` solo es obligatoria si querés que el scraper auto-genere reglas
> para campos desconocidos. Sin ella, el scraper funciona con las reglas base
> pero no puede aprender reglas nuevas.

### Ejemplo de .env mínimo

```env
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
MONOLITO_URL=http://mi-api.ejemplo.com:3000
```

### Ejemplo de .env completo

```env
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
MONOLITO_URL=http://mi-api.ejemplo.com:3000
MAX_WORKERS=8
PARALELO=true
LOG_LEVEL=DEBUG
REGLAS_PATH=reglas/reglas.toml
BODY_MAPPING_PATH=body_mapping.toml
```

> **⚠️ Seguridad:** El archivo `.env` está en `.gitignore` y **nunca debe commitearse**.
> Solo se commitea `.env.example` como template sin secrets.

---

## Esquema canónico

Toda propiedad extraída se normaliza al modelo `Propiedad` (Pydantic v2).
Definido en `scraper/schema.py`.

### Campos obligatorios

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | `UUID4` | Identificador único (auto-generado) |
| `fuente` | `str` | Nombre del sitio (ej: "argenprop", "zonaprop") |
| `url_origen` | `str` | URL de la propiedad scrapeada |
| `tipo` | `enum` | `casa` · `apto` · `terreno` · `comercial` · `otro` |
| `operacion` | `enum` | `venta` · `alquiler` |
| `scraped_at` | `datetime` | Timestamp UTC del scraping (auto-generado) |
| `precio_raw` | `str` | **Precio tal cual aparece en el sitio — NUNCA se descarta** |
| `pais` | `str` | Código de país (ej: "AR", "BO") |

### Campos de precio (opcionales)

| Campo | Tipo | Descripción |
|---|---|---|
| `precio_usd` | `float \| None` | Precio normalizado en USD |
| `precio_local` | `float \| None` | Precio en moneda local |
| `moneda_local` | `str \| None` | Código de moneda ("ARS", "BOB", etc.) |
| `precio_consultable` | `bool` | `True` si el precio es "Consultar" / "A consultar" |
| `expensas` | `float \| None` | Monto de expensas |

### Campos de ubicación

| Campo | Tipo | Descripción |
|---|---|---|
| `lat` | `float \| None` | Latitud (-90 a 90) |
| `lng` | `float \| None` | Longitud (-180 a 180) |
| `geo_confianza` | `enum` | `leaflet` · `iframe` · `ausente` — origen de las coords |
| `direccion_raw` | `str \| None` | Dirección tal cual aparece en el sitio |
| `ciudad` | `str \| None` | Ciudad |

### Campos de superficie y características

| Campo | Tipo | Descripción |
|---|---|---|
| `m2_total` | `float \| None` | Superficie total |
| `m2_cubierto` | `float \| None` | Superficie cubierta |
| `m2_terreno` | `float \| None` | Superficie del terreno |
| `ambientes` | `int \| None` | Cantidad de ambientes |
| `dormitorios` | `int \| None` | Cantidad de dormitorios |
| `banos` | `int \| None` | Cantidad de baños |
| `cocheras` | `int \| None` | Cantidad de cocheras |
| `antiguedad` | `int \| None` | Años de antigüedad |
| `estado` | `str \| None` | Estado de la propiedad |
| `amenities` | `list[str]` | Lista de amenities |

### Meta scraping

| Campo | Tipo | Descripción |
|---|---|---|
| `reglas_aplicadas` | `list[str]` | Nombres de reglas que se aplicaron |
| `campos_sin_resolver` | `list[str]` | Campos que no pudieron resolverse |
| `llm_usado` | `bool` | Si se usó el LLM para inferir reglas |
| `confianza_global` | `float` | Score de confianza (0.0–1.0) |
| `raw_payload` | `dict` | Payload crudo original (para debug) |

### 🔴 Regla de oro

> **`precio_raw` NUNCA se descarta.**
> Si el sitio dice "Consultar precio", entonces `precio_raw="Consultar precio"` y `precio_consultable=True`.
> Aunque no se pueda normalizar el precio, el valor original siempre se preserva.

---

## Motor de reglas

El corazón del scraper es un motor de reglas **Steel/Scheme embebido en Rust**,
expuesto a Python via PyO3.

### ¿Cómo funciona?

1. Al inicializarse, `MotorReglas` lee `reglas/reglas.toml` y carga los archivos `.scm`
2. Cada regla define una función `(define (aplicar campos) ...)` en Scheme
3. Al llamar `motor.aplicar(campos, fuente)`, se evalúan todas las reglas que:
   - Son **globales** (sin `fuente` definida), o
   - Coinciden con la **fuente** del sitio
4. Las reglas pueden ser **generadas por el LLM** en runtime y se persisten automáticamente

### Evaluación granular (sandbox aislado)

Cada regla se evalúa en un **Engine Steel aislado** (un VM fresco por regla):

```
┌────────────────────────────────────────────┐
│        evaluar_regla(codigo, campos)       │
│                                            │
│  1. Engine::new()           ← VM fresco    │
│  2. vm.register_fn(...)     ← 6 helpers    │
│  3. vm.run(codigo)          ← carga .scm   │
│  4. json_to_steel(campos)   ← JSON→Steel   │
│  5. vm.call("aplicar", ...) ← ejecuta      │
│  6. steel_to_json(result)   ← Steel→JSON   │
└────────────────────────────────────────────┘
```

- **Sin estado compartido** entre reglas — cada una es un sandbox.
- Si una regla falla, se loggea y se **continúa con la siguiente** (degradación controlada).
- La conversión `JSON ↔ SteelVal` soporta strings, números, booleanos, arrays, hashes y null.

### Helpers Rust registrados en Scheme

Los archivos `.scm` **no implementan regex ni parsing** directamente.
En su lugar, delegan a funciones Rust registradas con `vm.register_fn()`:

| Función Scheme | Firma Rust | Qué hace |
|---|---|---|
| `(parse-leaflet-center str)` | `String → Option<Vec<f64>>` | Parsea `"lat,lng"` → `(lat lng)` o `#f` |
| `(parse-gmaps-coords str)` | `String → Option<Vec<f64>>` | Parsea iframe GMaps (`!2d!3d` o `?q=`) → `(lat lng)` o `#f` |
| `(es-consultable? str)` | `String → bool` | Detecta "consultar"/"consulte" en precio_raw |
| `(extraer-monto-usd str)` | `String → Option<f64>` | Extrae monto de `"USD 150.000"` / `"U$S 150,000"` |
| `(extraer-monto-local str)` | `String → Option<f64>` | Extrae monto de `"$ 50.000.000"` |
| `(parse-numero-ar str)` | `String → Option<f64>` | Parsea formato argentino/boliviano (`1.500,50` → `1500.5`) |

Esto mantiene los `.scm` **cortos y declarativos** (5-15 líneas), delegando la complejidad a Rust compilado.

### Ejemplo de regla base (precio.scm)

```scheme
(define (aplicar campos)
  (let ((raw (hash-try-get campos "precio_raw")))
    (if (not raw)
        campos
        (let ((result campos))
          ;; Consultable?
          (let ((result (if (es-consultable? raw)
                            (hash-insert result "precio_consultable" #t)
                            result)))
            ;; Monto USD
            (let ((usd (extraer-monto-usd raw)))
              (let ((result (if usd (hash-insert result "precio_usd" usd) result)))
                ;; Monto local
                (let ((loc (extraer-monto-local raw)))
                  (if loc
                      (hash-insert (hash-insert result "precio_local" loc)
                                   "moneda_local" "ARS")
                      result)))))))))
```

### Índice de reglas (reglas.toml)

```toml
[[regla]]
nombre    = "leaflet"           # Identificador único
archivo   = "base/leaflet.scm"  # Ruta relativa al .scm
activa    = true                # Se puede desactivar sin borrar
confianza = 0.8                 # Score de confianza (0.0–1.0)
# fuente = "argenprop"          # Omitir = regla global
```

### Reglas base incluidas

| Regla | Archivo | Qué hace |
|---|---|---|
| `leaflet` | `base/leaflet.scm` | Extrae lat/lng del estado interno de Leaflet (`"lat,lng"`) |
| `gmaps` | `base/gmaps.scm` | Extrae lat/lng de iframe Google Maps (formatos `!2d!3d` y `?q=`) |
| `precio` | `base/precio.scm` | Normaliza `precio_raw` a USD/local/consultable |

### API Python del motor

```python
from scraper._scraper_core import MotorReglas

motor = MotorReglas("reglas/reglas.toml")

# Evaluar reglas sobre un dict de campos
resultado = motor.aplicar({"precio_raw": "USD 150.000"}, "argenprop")

# Verificar si existe una regla para un campo
motor.tiene_regla("leaflet", "zonaprop")  # True (es global)

# Agregar una regla nueva (se persiste en disco)
motor.agregar_regla(
    "mi_regla",                              # nombre
    '(define (aplicar campos) campos)',      # código Scheme
    "argenprop",                             # fuente (None = global)
    0.5,                                     # confianza
)
```

---

## Body mapping configurable

El scraper transforma la `Propiedad` normalizada antes de enviarla al monolito.
El mapping se define en `body_mapping.toml` y permite adaptar el body del POST
**sin tocar código Python ni recompilar**.

### ¿Por qué?

El esquema interno (`Propiedad`) no necesariamente coincide con el que espera la API destino.
Por ejemplo, la API puede esperar `id_propiedad` en vez de `id`, o `construccion_m2` en vez de `m2_cubierto`.

### Formato del archivo

```toml
# body_mapping.toml — Mapping Propiedad → body POST monolito

[campos]
# destino = "origen"    (campo directo)
# destino = "template"  (interpolación con {campo})
id_propiedad     = "id"
nombre_propiedad = "{operacion}-{tipo}-{ciudad}-{id}"
precio_bob       = "precio_local"
precio_usd       = "precio_usd"
direccion        = "direccion_raw"
zona             = "ciudad"
latitud          = "lat"
longitud         = "lng"
construccion_m2  = "m2_cubierto"
terreno_m2       = "m2_terreno"
habitaciones     = "dormitorios"
banos            = "banos"
garaje           = "cocheras"
tipo_propiedad   = "tipo"
tipo_operacion   = "operacion"
fuente           = "fuente"
url              = "url_origen"

[defaults]
# Valores por defecto si el campo origen es None o no existe
estado      = "disponible"
moneda      = "BOB"
descripcion = ""
```

### Interpolación de templates

Si el valor contiene `{campo}`, se interpola con los valores de la Propiedad:

```
nombre_propiedad = "{operacion}-{tipo}-{ciudad}-{id}"
```

Con una propiedad `operacion="venta"`, `tipo="casa"`, `ciudad="Cochabamba"`, `id="abc-123"`:

```json
"nombre_propiedad": "venta-casa-Cochabamba-abc-123"
```

Si algún campo del template es `None`, se reemplaza por string vacío.

### Configurar la ruta

Por defecto busca `body_mapping.toml` en la raíz del proyecto.
Se puede cambiar con la variable de entorno `BODY_MAPPING_PATH`:

```env
BODY_MAPPING_PATH=config/mi_mapping.toml
```

---

## BrowserPool

Implementado en `scraper/pool.py`. Maneja **un solo browser Chromium headless**
con N contextos concurrentes controlados por un `asyncio.Semaphore`.

### Comportamiento

- **1 browser** Chromium con flags: `--no-sandbox --disable-dev-shm-usage --disable-gpu --single-process`
- **N contextos** (default 4) controlados por `Semaphore(workers)`
- Cada tarea pide un contexto via `async with pool.context()`
- El contexto se **cierra automáticamente** al salir del bloque
- Implementado como **async context manager** (`__aenter__` / `__aexit__`)

### Uso directo

```python
from scraper.pool import BrowserPool

async with BrowserPool(workers=4) as pool:
    async with pool.context() as ctx:
        page = await ctx.new_page()
        await page.goto("https://ejemplo.com")
        html = await page.content()
        await page.close()
```

### ¿Por qué no múltiples browsers?

Un browser con N contextos es más eficiente en memoria que N browsers separados.
Cada contexto tiene su propia sesión (cookies, storage) pero comparten el proceso del browser.

---

## Pipeline de normalización

Implementado en `scraper/normalizador.py`. Orquesta toda la cadena de extracción:

```
HTML crudo
    │
    ▼
┌─────────────────────┐
│ Extractor (Rust)    │──→ coords Leaflet/GMaps + precio normalizado
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ MotorReglas (Steel) │──→ evalúa reglas .scm que matchean la fuente
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│ Detección campos    │──→ identifica qué campos quedaron sin resolver
│ sin resolver        │
└─────────────────────┘
    │ (si hay campos sin resolver Y GROQ_API_KEY configurada)
    ▼
┌─────────────────────┐
│ LLM Groq            │──→ genera reglas Scheme nuevas
│ (fallback)          │──→ las persiste en reglas/sitios/<fuente>/
└─────────────────────┘
    │
    ▼
  Propiedad (esquema canónico)
```

### Campos que el pipeline intenta resolver automáticamente

`precio_usd` · `precio_local` · `moneda_local` · `precio_consultable` · `lat` · `lng` · `geo_confianza`

---

## Cliente LLM

Implementado en `scraper/llm.py`. Usa **Groq** con el modelo `llama-3.3-70b-versatile`.

### ¿Cuándo se invoca?

Solo cuando el Extractor + MotorReglas dejan **campos sin resolver** y `GROQ_API_KEY` está configurada en `.env`.

### ¿Qué hace?

1. Envía un prompt con el esquema canónico destino y las reglas existentes como ejemplo
2. Pide al LLM que genere **una regla Scheme por campo desconocido**
3. Exige que la respuesta sea SOLO código Scheme válido, sin explicaciones ni markdown
4. Valida que la respuesta sea parseable (paréntesis balanceados, contiene `define`)
5. Si falla el parse, **reintenta una vez** con el error incluido en el mensaje
6. Las reglas válidas se persisten en `reglas/sitios/<fuente>/`

### Seguridad

El LLM solo genera código Scheme declarativo. Las reglas se evalúan en el sandbox de Steel
(sin acceso a filesystem, red, ni sistema operativo).

---

## Cliente HTTP (monolito)

Implementado en `scraper/cliente.py`. Envía propiedades normalizadas al monolito.

| Parámetro | Valor |
|---|---|
| Método | `POST` |
| URL | `{MONOLITO_URL}/propiedades` |
| Formato | JSON transformado según `body_mapping.toml` |
| Timeout | 30 segundos |
| Reintentos | 3 con backoff exponencial (1s → 2s → 4s) |
| Reintentar en | 5xx, timeout |
| No reintentar en | 4xx, errores de red irrecuperables |
| Logging | `url_origen` y `fuente` en cada request |

### Body mapping

Antes de enviar, `transformar_body(propiedad)` convierte la `Propiedad` al formato
que espera la API destino usando `body_mapping.toml`:

```python
# Propiedad interna                → Body POST al monolito
{                                    {
  "id": "abc-123",                     "id_propiedad": "abc-123",
  "precio_local": 150000,             "precio_bob": 150000,
  "m2_cubierto": 120.0,               "construccion_m2": 120.0,
  "operacion": "venta",               "nombre_propiedad": "venta-casa-...",
  ...                                  ...
}                                    }
```

Si no existe `body_mapping.toml`, se envía `propiedad.model_dump()` sin transformar (fallback).

---

## Tests

### Correr tests

```bash
# Todos los tests (requiere el flag para Python 3.13+)
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 uv run pytest tests/ -v

# Solo tests de precio
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 uv run pytest tests/test_motor.py::TestPrecio -v

# Solo tests de Google Maps
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 uv run pytest tests/test_motor.py::TestGmaps -v

# Solo tests de schema
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 uv run pytest tests/test_motor.py::TestSchema -v
```

### Tests incluidos (12 total)

| Clase | Test | Qué verifica |
|---|---|---|
| `TestGmaps` | `test_gmaps_formato_embed` | `!2d{lng}!3d{lat}` extrae coords correctas |
| `TestGmaps` | `test_gmaps_formato_q` | `?q=lat,lng` extrae coords correctas |
| `TestLeaflet` | `test_leaflet_center` | `"lat,lng"` se parsea correctamente |
| `TestLeaflet` | `test_leaflet_con_espacios` | Soporta espacios alrededor de la coma |
| `TestLeaflet` | `test_leaflet_fuera_de_rango` | lat > 90 lanza `ValueError` |
| `TestPrecio` | `test_precio_usd` | `"USD 150.000"` → `precio_usd=150000.0` |
| `TestPrecio` | `test_precio_uss` | `"U$S 150,000"` → `precio_usd=150000.0` |
| `TestPrecio` | `test_precio_consultable` | `"Consultar precio"` → `precio_consultable=True` |
| `TestPrecio` | `test_precio_a_consultar` | `"A consultar"` → `precio_consultable=True` |
| `TestPrecio` | `test_precio_local` | `"$ 50.000.000"` → `precio_local=50000000.0` |
| `TestSchema` | `test_propiedad_minima` | Propiedad se crea con campos mínimos |
| `TestSchema` | `test_precio_raw_nunca_se_descarta` | `precio_raw` se preserva siempre |

### Fixtures HTML

Disponibles en `tests/fixtures/` para tests de integración futuros:

- `gmaps_embed.html` — página con iframe Google Maps embed
- `gmaps_query.html` — página con iframe Google Maps query
- `leaflet.html` — página con mapa Leaflet

---

## Uso

### Ejemplo mínimo — Extractor Rust desde Python

```python
from scraper._scraper_core import Extractor

e = Extractor()

# Normalizar precio
e.normalizar_precio("USD 150.000")
# → {'precio_usd': 150000.0, 'precio_local': None, 'moneda_local': None, 'precio_consultable': False}

e.normalizar_precio("$ 50.000.000")
# → {'precio_usd': None, 'precio_local': 50000000.0, 'moneda_local': 'ARS', 'precio_consultable': False}

e.normalizar_precio("Consultar precio")
# → {'precio_usd': None, 'precio_local': None, 'moneda_local': None, 'precio_consultable': True}

# Extraer coords de Google Maps
e.extraer_gmaps("https://maps.google.com/maps?q=-34.6037,-58.3816")
# → (-34.6037, -58.3816)

# Extraer coords de Leaflet
e.extraer_leaflet("-34.6037,-58.3816")
# → (-34.6037, -58.3816)
```

### Ejemplo — Scraping completo (requiere Playwright + .env)

```python
import asyncio
from scraper.runner import run, SitioConfig

sitios = [
    SitioConfig(nombre="argenprop", url="https://www.argenprop.com/...", pais="AR"),
    SitioConfig(nombre="zonaprop",  url="https://www.zonaprop.com.ar/...", pais="AR"),
]

propiedades = asyncio.run(run(sitios, paralelo=True, workers=4))

for p in propiedades:
    print(f"{p.fuente}: {p.precio_raw} → USD {p.precio_usd}")
```

### Ejemplo — Crear una Propiedad manualmente

```python
from scraper.schema import Propiedad, TipoPropiedad, Operacion

p = Propiedad(
    fuente="manual",
    url_origen="https://ejemplo.com/casa-1",
    tipo=TipoPropiedad.casa,
    operacion=Operacion.venta,
    precio_raw="USD 250.000",
    pais="AR",
    precio_usd=250000.0,
    lat=-34.6037,
    lng=-58.3816,
)

print(p.model_dump_json(indent=2))
```

---

## Decisiones de diseño

| Decisión | Razón |
|---|---|
| **asyncio puro** (sin Redis/Celery) | Simplicidad. Un solo proceso, sin broker externo. |
| **1 browser, N contextos** (sin múltiples browsers) | Más eficiente en memoria. Contextos aislados comparten proceso. |
| **Reglas en archivos .scm** (sin hardcodear en Python/Rust) | Extensibles sin recompilar. El LLM las genera en runtime. |
| **Engine aislado por regla** (sin VM compartida) | Sandbox real. Una regla malformada no afecta a las demás. |
| **Helpers Rust en Scheme** (sin regex en .scm) | Parsing pesado en Rust compilado, reglas declarativas y cortas. |
| **Body mapping TOML** (sin hardcodear en cliente.py) | Adaptar el body del POST sin tocar código ni recompilar. |
| **httpx** (sin requests) | Nativo async, no bloquea el event loop. |
| **Steel/Scheme** (sin Lua/WASM) | Funcional puro, sandboxeable, expresivo para transformaciones. |
| **pydantic-settings + .env** | Estándar 12-factor. Fácil en local y en deploy. |
| **Groq** (sin OpenAI directo) | Latencia ~200ms con llama-3.3-70b. Ideal en el loop de scraping. |
| **precio_raw siempre se preserva** | Dato inmutable. Permite re-normalizar sin re-scrapear. |
| **Sin numpy** | No hay operaciones vectoriales. Solo string parsing. |

---

## Dependencias

### Python (pyproject.toml)

| Paquete | Versión | Propósito |
|---|---|---|
| `playwright` | ≥1.44 | Captura web con Chromium headless |
| `pydantic` | ≥2.7 | Esquema canónico + validación |
| `pydantic-settings` | ≥2.0 | Configuración desde env vars y `.env` |
| `httpx` | ≥0.27 | POST async al monolito |
| `toml` | ≥0.10 | Carga reglas.toml |
| `apscheduler` | ≥3.10 | Scheduler cron |
| `groq` | ≥0.9 | Cliente LLM |
| `pytest` | ≥9.0 | Tests |

### Rust (Cargo.toml)

| Crate | Versión | Propósito |
|---|---|---|
| `pyo3` | 0.21 | Bindings Python ↔ Rust |
| `steel-core` | 0.8 | Intérprete Scheme embebido |
| `scraper` | 0.19 | Parsing HTML (crate, no el proyecto) |
| `serde` + `serde_json` | 1 | Serialización JSON |
| `toml` | 0.8 | Parsing del índice de reglas |
| `regex` | 1 | Patrones de extracción |

---

## Licencia

Pendiente.
