"""
schema.py — Esquema canónico Pydantic v2 para propiedades inmobiliarias.

Regla de oro: precio_raw NUNCA se descarta.
Si el sitio dice "Consultar precio", precio_raw="Consultar precio"
y precio_consultable=True.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TipoPropiedad(str, Enum):
    casa = "casa"
    apto = "apto"
    terreno = "terreno"
    comercial = "comercial"
    otro = "otro"


class Operacion(str, Enum):
    venta = "venta"
    alquiler = "alquiler"


class GeoConfianza(str, Enum):
    leaflet = "leaflet"
    iframe = "iframe"
    ausente = "ausente"


class Propiedad(BaseModel):
    """Esquema canónico de una propiedad inmobiliaria."""

    # ── Campos obligatorios ───────────────────────────────────────────────
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    fuente: str
    url_origen: str
    tipo: TipoPropiedad
    operacion: Operacion
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    precio_raw: str  # NUNCA se descarta
    pais: str

    # ── Precio ────────────────────────────────────────────────────────────
    precio_usd: Optional[float] = None
    precio_local: Optional[float] = None
    moneda_local: Optional[str] = None
    precio_consultable: bool = False
    expensas: Optional[float] = None

    # ── Ubicación ─────────────────────────────────────────────────────────
    lat: Optional[float] = None
    lng: Optional[float] = None
    geo_confianza: GeoConfianza = GeoConfianza.ausente
    direccion_raw: Optional[str] = None
    ciudad: Optional[str] = None

    # ── Superficie y características ──────────────────────────────────────
    m2_total: Optional[float] = None
    m2_cubierto: Optional[float] = None
    m2_terreno: Optional[float] = None
    ambientes: Optional[int] = None
    dormitorios: Optional[int] = None
    banos: Optional[int] = None
    cocheras: Optional[int] = None
    antiguedad: Optional[int] = None
    estado: Optional[str] = None
    amenities: list[str] = Field(default_factory=list)

    # ── Meta scraping ─────────────────────────────────────────────────────
    reglas_aplicadas: list[str] = Field(default_factory=list)
    campos_sin_resolver: list[str] = Field(default_factory=list)
    llm_usado: bool = False
    confianza_global: float = 0.0
    raw_payload: dict = Field(default_factory=dict)
