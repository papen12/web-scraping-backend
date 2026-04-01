use pyo3::prelude::*;
use regex::Regex;

// ── Resultado de normalización de precio ─────────────────────────────────────

#[derive(Debug, Clone)]
pub struct PrecioNormalizado {
    pub precio_usd: Option<f64>,
    pub precio_local: Option<f64>,
    pub moneda_local: Option<String>,
    pub precio_consultable: bool,
}

// ── Extractor ────────────────────────────────────────────────────────────────

#[pyclass]
pub struct Extractor {
    re_embed: Regex,
    re_query: Regex,
    re_usd: Regex,
    re_local: Regex,
    re_consultar: Regex,
    re_numero: Regex,
}

impl Extractor {
    pub fn new() -> Self {
        Extractor {
            // Google Maps embed format: !2d{lng}!3d{lat}
            re_embed: Regex::new(r"!2d(-?[\d.]+)!3d(-?[\d.]+)").unwrap(),
            // Google Maps query format: q={lat},{lng}
            re_query: Regex::new(r"[?&]q=(-?[\d.]+),(-?[\d.]+)").unwrap(),
            // USD variants: "USD 150.000", "U$S 150,000", "US$ 150.000"
            re_usd: Regex::new(r"(?i)(?:USD|U\$S|US\$)\s*([\d.,]+)").unwrap(),
            // Local currency: "$ 50.000.000"
            re_local: Regex::new(r"^\$\s*([\d.,]+)").unwrap(),
            // Consult price
            re_consultar: Regex::new(r"(?i)(?:a\s+)?consult(?:ar|e)?").unwrap(),
            // Generic number extraction
            re_numero: Regex::new(r"[\d.,]+").unwrap(),
        }
    }

    /// Extraer lat/lng del estado interno de Leaflet.
    /// Espera formato "lat,lng".
    pub fn extraer_leaflet(&self, js_center: &str) -> Result<(f64, f64), String> {
        let parts: Vec<&str> = js_center.split(',').collect();
        if parts.len() != 2 {
            return Err(format!(
                "Formato inválido de leaflet center: '{}'. Esperado: 'lat,lng'",
                js_center
            ));
        }

        let lat: f64 = parts[0]
            .trim()
            .parse()
            .map_err(|_| format!("lat no parseable: '{}'", parts[0].trim()))?;
        let lng: f64 = parts[1]
            .trim()
            .parse()
            .map_err(|_| format!("lng no parseable: '{}'", parts[1].trim()))?;

        if !(-90.0..=90.0).contains(&lat) {
            return Err(format!("lat fuera de rango (-90, 90): {lat}"));
        }
        if !(-180.0..=180.0).contains(&lng) {
            return Err(format!("lng fuera de rango (-180, 180): {lng}"));
        }

        Ok((lat, lng))
    }

    /// Extraer lat/lng de URL de iframe Google Maps.
    /// Soporta !2d{lng}!3d{lat} y q={lat},{lng}.
    pub fn extraer_gmaps(&self, iframe_src: &str) -> Result<(f64, f64), String> {
        // Try embed format first: !2d{lng}!3d{lat}
        if let Some(caps) = self.re_embed.captures(iframe_src) {
            let lng: f64 = caps[1]
                .parse()
                .map_err(|_| format!("lng no parseable en embed: '{}'", &caps[1]))?;
            let lat: f64 = caps[2]
                .parse()
                .map_err(|_| format!("lat no parseable en embed: '{}'", &caps[2]))?;
            return Ok((lat, lng));
        }

        // Try query format: q={lat},{lng}
        if let Some(caps) = self.re_query.captures(iframe_src) {
            let lat: f64 = caps[1]
                .parse()
                .map_err(|_| format!("lat no parseable en query: '{}'", &caps[1]))?;
            let lng: f64 = caps[2]
                .parse()
                .map_err(|_| format!("lng no parseable en query: '{}'", &caps[2]))?;
            return Ok((lat, lng));
        }

        Err(format!(
            "No se encontraron coordenadas en iframe src: '{}'",
            iframe_src
        ))
    }

    /// Normalizar precio_raw a componentes estructurados.
    ///
    /// Regla de oro: precio_raw NUNCA se descarta.
    pub fn normalizar_precio(&self, precio_raw: &str) -> PrecioNormalizado {
        let trimmed = precio_raw.trim();

        // Caso "Consultar"
        if self.re_consultar.is_match(trimmed) {
            return PrecioNormalizado {
                precio_usd: None,
                precio_local: None,
                moneda_local: None,
                precio_consultable: true,
            };
        }

        // Caso USD
        if let Some(caps) = self.re_usd.captures(trimmed) {
            let num_str = &caps[1];
            if let Some(val) = Self::parse_numero_ar(num_str) {
                return PrecioNormalizado {
                    precio_usd: Some(val),
                    precio_local: None,
                    moneda_local: None,
                    precio_consultable: false,
                };
            }
        }

        // Caso moneda local ($ ...)
        if let Some(caps) = self.re_local.captures(trimmed) {
            let num_str = &caps[1];
            if let Some(val) = Self::parse_numero_ar(num_str) {
                return PrecioNormalizado {
                    precio_usd: None,
                    precio_local: Some(val),
                    moneda_local: Some("ARS".to_string()),
                    precio_consultable: false,
                };
            }
        }

        // Fallback: no se pudo parsear, pero NO descartamos precio_raw
        PrecioNormalizado {
            precio_usd: None,
            precio_local: None,
            moneda_local: None,
            precio_consultable: false,
        }
    }

    /// Parsear número en formato argentino/boliviano.
    /// Puntos como separador de miles, coma como decimal.
    /// "150.000" → 150000.0
    /// "50.000.000" → 50000000.0
    /// "150,000" → 150000.0 (si es único separador, asumir miles)
    fn parse_numero_ar(s: &str) -> Option<f64> {
        let trimmed = s.trim();
        if trimmed.is_empty() {
            return None;
        }

        let has_dot = trimmed.contains('.');
        let has_comma = trimmed.contains(',');

        let normalized = if has_dot && has_comma {
            // "150.000,50" → dots are thousands, comma is decimal
            trimmed.replace('.', "").replace(',', ".")
        } else if has_dot {
            // Count dots — if multiple, they're thousands separators
            let dot_count = trimmed.matches('.').count();
            if dot_count > 1 {
                // "50.000.000" → thousands separators
                trimmed.replace('.', "")
            } else {
                // Single dot: check position from right
                // "150.000" (3 digits after dot) → thousands separator
                // "150.50" (2 digits after dot) → decimal
                let after_dot = trimmed.split('.').last().unwrap_or("");
                if after_dot.len() == 3 {
                    trimmed.replace('.', "")
                } else {
                    trimmed.to_string()
                }
            }
        } else if has_comma {
            // "150,000" → could be thousands or decimal
            let after_comma = trimmed.split(',').last().unwrap_or("");
            if after_comma.len() == 3 {
                trimmed.replace(',', "")
            } else {
                trimmed.replace(',', ".")
            }
        } else {
            trimmed.to_string()
        };

        normalized.parse::<f64>().ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_leaflet_ok() {
        let ext = Extractor::new();
        let (lat, lng) = ext.extraer_leaflet("-34.6037,  -58.3816").unwrap();
        assert!((lat - (-34.6037)).abs() < 1e-4);
        assert!((lng - (-58.3816)).abs() < 1e-4);
    }

    #[test]
    fn test_gmaps_embed() {
        let ext = Extractor::new();
        let src = "https://www.google.com/maps/embed?pb=!1m18!2d-58.3816!3d-34.6037";
        let (lat, lng) = ext.extraer_gmaps(src).unwrap();
        assert!((lat - (-34.6037)).abs() < 1e-4);
        assert!((lng - (-58.3816)).abs() < 1e-4);
    }

    #[test]
    fn test_gmaps_query() {
        let ext = Extractor::new();
        let src = "https://maps.google.com/maps?q=-34.6037,-58.3816&z=15";
        let (lat, lng) = ext.extraer_gmaps(src).unwrap();
        assert!((lat - (-34.6037)).abs() < 1e-4);
        assert!((lng - (-58.3816)).abs() < 1e-4);
    }

    #[test]
    fn test_precio_usd() {
        let ext = Extractor::new();
        let r = ext.normalizar_precio("USD 150.000");
        assert_eq!(r.precio_usd, Some(150000.0));
        assert!(!r.precio_consultable);
    }

    #[test]
    fn test_precio_usd_uss() {
        let ext = Extractor::new();
        let r = ext.normalizar_precio("U$S 150,000");
        assert_eq!(r.precio_usd, Some(150000.0));
    }

    #[test]
    fn test_precio_local() {
        let ext = Extractor::new();
        let r = ext.normalizar_precio("$ 50.000.000");
        assert_eq!(r.precio_local, Some(50000000.0));
        assert_eq!(r.moneda_local.as_deref(), Some("ARS"));
    }

    #[test]
    fn test_precio_consultar() {
        let ext = Extractor::new();
        let r = ext.normalizar_precio("Consultar precio");
        assert!(r.precio_consultable);
        assert_eq!(r.precio_usd, None);
    }

    #[test]
    fn test_precio_a_consultar() {
        let ext = Extractor::new();
        let r = ext.normalizar_precio("A consultar");
        assert!(r.precio_consultable);
    }
}
