"""
test_motor.py — Tests del motor de extracción y reglas.

Usa el Extractor Rust (via scraper_core) para validar:
- Extracción de coords de Google Maps (embed y query)
- Extracción de coords de Leaflet
- Normalización de precios (USD, local, consultable)
"""

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_extractor():
    """Importa y retorna el Extractor Rust. Skip si no está compilado."""
    try:
        import scraper._scraper_core as scraper_core
        return scraper_core.Extractor()
    except ImportError:
        pytest.skip("scraper_core no compilado. Ejecutar: maturin develop --release")


# ── Tests Google Maps ─────────────────────────────────────────────────────────

class TestGmaps:
    def test_gmaps_formato_embed(self):
        """iframe embed con !2d{lng}!3d{lat} extrae lat/lng correctos."""
        ext = _get_extractor()
        iframe_src = (
            "https://www.google.com/maps/embed?pb="
            "!1m18!1m12!1m3!1d3283.9!2d-58.3816!3d-34.6037!2m3!1f0!2f0!3f0"
        )
        lat, lng = ext.extraer_gmaps(iframe_src)
        assert abs(lat - (-34.6037)) < 1e-4
        assert abs(lng - (-58.3816)) < 1e-4

    def test_gmaps_formato_q(self):
        """URL con ?q=lat,lng extrae lat/lng correctos."""
        ext = _get_extractor()
        iframe_src = "https://maps.google.com/maps?q=-34.6037,-58.3816&z=15"
        lat, lng = ext.extraer_gmaps(iframe_src)
        assert abs(lat - (-34.6037)) < 1e-4
        assert abs(lng - (-58.3816)) < 1e-4


# ── Tests Leaflet ─────────────────────────────────────────────────────────────

class TestLeaflet:
    def test_leaflet_center(self):
        """js_leaflet_center con lat,lng se parsea correctamente."""
        ext = _get_extractor()
        lat, lng = ext.extraer_leaflet("-34.6037,-58.3816")
        assert abs(lat - (-34.6037)) < 1e-4
        assert abs(lng - (-58.3816)) < 1e-4

    def test_leaflet_con_espacios(self):
        """Soporta espacios alrededor de la coma."""
        ext = _get_extractor()
        lat, lng = ext.extraer_leaflet("-34.6037 , -58.3816")
        assert abs(lat - (-34.6037)) < 1e-4
        assert abs(lng - (-58.3816)) < 1e-4

    def test_leaflet_fuera_de_rango(self):
        """lat fuera de rango lanza error."""
        ext = _get_extractor()
        with pytest.raises(ValueError):
            ext.extraer_leaflet("999.0,-58.3816")


# ── Tests Precio ──────────────────────────────────────────────────────────────

class TestPrecio:
    def test_precio_usd(self):
        """'USD 150.000' → precio_usd=150000.0"""
        ext = _get_extractor()
        result = ext.normalizar_precio("USD 150.000")
        assert result["precio_usd"] == 150000.0
        assert result["precio_consultable"] is False

    def test_precio_uss(self):
        """'U$S 150,000' → precio_usd=150000.0"""
        ext = _get_extractor()
        result = ext.normalizar_precio("U$S 150,000")
        assert result["precio_usd"] == 150000.0

    def test_precio_consultable(self):
        """'Consultar precio' → precio_consultable=True"""
        ext = _get_extractor()
        result = ext.normalizar_precio("Consultar precio")
        assert result["precio_consultable"] is True
        assert result["precio_usd"] is None

    def test_precio_a_consultar(self):
        """'A consultar' → precio_consultable=True"""
        ext = _get_extractor()
        result = ext.normalizar_precio("A consultar")
        assert result["precio_consultable"] is True

    def test_precio_local(self):
        """'$ 50.000.000' → precio_local=50000000.0, moneda_local=ARS"""
        ext = _get_extractor()
        result = ext.normalizar_precio("$ 50.000.000")
        assert result["precio_local"] == 50000000.0
        assert result["moneda_local"] == "ARS"


# ── Tests Schema ──────────────────────────────────────────────────────────────

class TestSchema:
    def test_propiedad_minima(self):
        """Se puede crear una Propiedad con campos mínimos obligatorios."""
        from scraper.schema import Propiedad, TipoPropiedad, Operacion

        p = Propiedad(
            fuente="test",
            url_origen="https://example.com/1",
            tipo=TipoPropiedad.casa,
            operacion=Operacion.venta,
            precio_raw="USD 100.000",
            pais="AR",
        )
        assert p.fuente == "test"
        assert p.precio_raw == "USD 100.000"
        assert p.precio_consultable is False
        assert p.confianza_global == 0.0
        assert p.reglas_aplicadas == []

    def test_precio_raw_nunca_se_descarta(self):
        """Regla de oro: precio_raw='Consultar' se preserva."""
        from scraper.schema import Propiedad, TipoPropiedad, Operacion

        p = Propiedad(
            fuente="test",
            url_origen="https://example.com/2",
            tipo=TipoPropiedad.otro,
            operacion=Operacion.alquiler,
            precio_raw="Consultar precio",
            precio_consultable=True,
            pais="AR",
        )
        assert p.precio_raw == "Consultar precio"
        assert p.precio_consultable is True
