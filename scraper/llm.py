"""
llm.py — Cliente Groq LLM para inferir reglas Scheme.

Modelo: llama-3.3-70b-versatile
Genera código Steel/Scheme válido para campos sin resolver.
"""

from __future__ import annotations

import logging
from typing import Any

from groq import Groq

from scraper.config import settings

logger = logging.getLogger(__name__)

# ── Prompt templates ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Eres un generador de reglas Steel/Scheme para un scraper inmobiliario.

El esquema canónico de destino tiene estos campos:
- precio_usd (float): precio en dólares
- precio_local (float): precio en moneda local
- moneda_local (str): código de moneda (ARS, BOB, etc.)
- precio_consultable (bool): true si el precio es "a consultar"
- lat (float): latitud (-90 a 90)
- lng (float): longitud (-180 a 180)
- geo_confianza (str): "leaflet", "iframe" o "ausente"
- direccion_raw (str): dirección tal como aparece
- ciudad (str): ciudad
- m2_total, m2_cubierto, m2_terreno (float): superficies
- ambientes, dormitorios, banos, cocheras (int): conteos
- antiguedad (int): años
- estado (str): estado de la propiedad

Cada regla Steel define una función `aplicar` que recibe un hash con campos
y devuelve un hash actualizado.

Sintaxis Steel/Scheme:
```scheme
(define (aplicar campos)
  (let ((valor (hash-ref campos "campo_entrada")))
    (if valor
      (hash-set campos "campo_destino" (transformar valor))
      campos)))
```

IMPORTANTE:
- Responde SOLO con código Scheme válido, sin explicaciones ni markdown.
- Una función `aplicar` por regla.
- Cada bloque de regla separado por una línea en blanco.
"""

USER_PROMPT_TEMPLATE = """\
Necesito reglas para la fuente "{fuente}".

Campos sin resolver y sus valores crudos:
{campos_str}

Reglas ya existentes (no repetir):
{reglas_str}

Genera UNA regla Steel/Scheme por campo sin resolver.
SOLO código Scheme, sin explicaciones ni markdown.
"""


def _build_prompt(
    campos_sin_resolver: dict[str, Any],
    fuente: str,
    reglas_existentes: list[str],
) -> str:
    campos_str = "\n".join(
        f"  - {campo}: {valor!r}" for campo, valor in campos_sin_resolver.items()
    )
    reglas_str = "\n".join(f"  - {r}" for r in reglas_existentes) or "  (ninguna)"
    return USER_PROMPT_TEMPLATE.format(
        fuente=fuente,
        campos_str=campos_str,
        reglas_str=reglas_str,
    )


def _parse_scheme_blocks(response: str) -> list[str]:
    """
    Separa la respuesta en bloques de código Scheme individuales.
    Cada bloque empieza con (define ...).
    """
    blocks: list[str] = []
    current: list[str] = []

    for line in response.strip().splitlines():
        stripped = line.strip()
        # Ignorar líneas markdown residuales
        if stripped.startswith("```"):
            continue
        if stripped.startswith("(define") and current:
            blocks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        blocks.append("\n".join(current))

    # Filtrar bloques vacíos
    return [b.strip() for b in blocks if b.strip() and "(define" in b]


def _validate_scheme(code: str) -> bool:
    """Validación básica: paréntesis balanceados y contiene 'define'."""
    if "define" not in code:
        return False
    depth = 0
    for ch in code:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth < 0:
            return False
    return depth == 0


def inferir_reglas(
    campos_sin_resolver: dict[str, Any],
    fuente: str,
    reglas_existentes: list[str],
) -> list[str]:
    """
    Usa Groq LLM para inferir reglas Scheme para campos sin resolver.

    Args:
        campos_sin_resolver: Dict campo → valor crudo del payload.
        fuente: Nombre del sitio fuente.
        reglas_existentes: Nombres de reglas ya aplicadas.

    Returns:
        Lista de strings, cada uno es código Scheme válido para una regla.
    """
    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY no configurada, saltando inferencia LLM")
        return []

    client = Groq(api_key=settings.groq_api_key)
    user_prompt = _build_prompt(campos_sin_resolver, fuente, reglas_existentes)

    for intento in range(2):
        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            if intento == 1:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "La respuesta anterior no era código Scheme válido. "
                            "Por favor responde SOLO con código Scheme válido, "
                            "sin markdown ni explicaciones."
                        ),
                    }
                )

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.2,
                max_tokens=2048,
            )

            content = response.choices[0].message.content or ""
            blocks = _parse_scheme_blocks(content)

            # Validar cada bloque
            valid_blocks = [b for b in blocks if _validate_scheme(b)]

            if valid_blocks:
                logger.info(
                    "LLM generó %d reglas válidas para %s (intento %d)",
                    len(valid_blocks),
                    fuente,
                    intento + 1,
                )
                return valid_blocks

            logger.warning(
                "LLM no generó reglas válidas (intento %d), blocks=%d",
                intento + 1,
                len(blocks),
            )

        except Exception as e:
            logger.error("Error llamando a Groq (intento %d): %s", intento + 1, e)

    return []
