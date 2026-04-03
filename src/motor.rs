use pyo3::prelude::*;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

// ── Tipos de configuración ───────────────────────────────────────────────────

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ReglaConfig {
    pub nombre: String,
    pub archivo: String,
    #[serde(default)]
    pub fuente: Option<String>,
    #[serde(default = "default_true")]
    pub activa: bool,
    #[serde(default = "default_confianza")]
    pub confianza: f64,
}

fn default_true() -> bool {
    true
}

fn default_confianza() -> f64 {
    0.5
}

#[derive(Debug, Deserialize, Serialize)]
struct ReglasToml {
    #[serde(default)]
    regla: Vec<ReglaConfig>,
}

// ── Conversión JSON ↔ SteelVal ───────────────────────────────────────────────

/// Convierte serde_json::Value → SteelVal para pasar al motor Steel.
fn json_to_steel(value: &serde_json::Value) -> Result<steel::rvals::SteelVal, String> {
    use steel::rvals::{IntoSteelVal, SteelVal};

    match value {
        serde_json::Value::Null => Ok(SteelVal::BoolV(false)),
        serde_json::Value::Bool(b) => Ok(SteelVal::BoolV(*b)),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(SteelVal::IntV(i as isize))
            } else {
                Ok(SteelVal::NumV(n.as_f64().unwrap_or(0.0)))
            }
        }
        serde_json::Value::String(s) => s.clone().into_steelval().map_err(|e| format!("{e}")),
        serde_json::Value::Array(arr) => {
            let items: Result<Vec<steel::rvals::SteelVal>, String> =
                arr.iter().map(json_to_steel).collect();
            items?.into_steelval().map_err(|e| format!("{e}"))
        }
        serde_json::Value::Object(map) => {
            let mut hm: HashMap<String, steel::rvals::SteelVal> = HashMap::new();
            for (k, v) in map {
                hm.insert(k.clone(), json_to_steel(v)?);
            }
            hm.into_steelval().map_err(|e| format!("{e}"))
        }
    }
}

/// Convierte SteelVal → serde_json::Value después de evaluación Steel.
fn steel_to_json(value: &steel::rvals::SteelVal) -> Result<serde_json::Value, String> {
    use steel::rvals::{FromSteelVal, SteelVal};

    match value {
        SteelVal::BoolV(b) => Ok(serde_json::Value::Bool(*b)),
        SteelVal::IntV(i) => Ok(serde_json::json!(*i)),
        SteelVal::NumV(f) => {
            if f.is_finite() {
                Ok(serde_json::json!(*f))
            } else {
                Ok(serde_json::Value::Null)
            }
        }
        SteelVal::StringV(s) => Ok(serde_json::Value::String(s.to_string())),
        SteelVal::Void => Ok(serde_json::Value::Null),
        SteelVal::HashMapV(_) => {
            let map: HashMap<String, SteelVal> =
                HashMap::from_steelval(value).map_err(|e| format!("Hash→JSON: {e}"))?;
            let mut json_map = serde_json::Map::new();
            for (k, v) in map {
                json_map.insert(k, steel_to_json(&v)?);
            }
            Ok(serde_json::Value::Object(json_map))
        }
        SteelVal::ListV(list) => {
            let items: Result<Vec<serde_json::Value>, String> =
                list.iter().map(steel_to_json).collect();
            Ok(serde_json::Value::Array(items?))
        }
        _ => Ok(serde_json::Value::Null),
    }
}

// ── Helpers Rust registrados en el motor Steel ───────────────────────────────
//
// Se registran con vm.register_fn(...) y quedan disponibles en Scheme.
// Las reglas .scm delegan la lógica pesada (regex, parsing) a estos helpers.

/// Parsea "lat,lng" de Leaflet → lista (lat lng) o #f.
fn helper_parse_leaflet(center: String) -> Option<Vec<f64>> {
    let parts: Vec<&str> = center.split(',').collect();
    if parts.len() != 2 {
        return None;
    }
    let lat: f64 = parts[0].trim().parse().ok()?;
    let lng: f64 = parts[1].trim().parse().ok()?;
    if !(-90.0..=90.0).contains(&lat) || !(-180.0..=180.0).contains(&lng) {
        return None;
    }
    Some(vec![lat, lng])
}

/// Parsea iframe src de Google Maps → lista (lat lng) o #f.
fn helper_parse_gmaps(src: String) -> Option<Vec<f64>> {
    let re_embed = Regex::new(r"!2d(-?[\d.]+)!3d(-?[\d.]+)").unwrap();
    let re_query = Regex::new(r"[?&]q=(-?[\d.]+),(-?[\d.]+)").unwrap();

    if let Some(caps) = re_embed.captures(&src) {
        let lng: f64 = caps[1].parse().ok()?;
        let lat: f64 = caps[2].parse().ok()?;
        return Some(vec![lat, lng]);
    }
    if let Some(caps) = re_query.captures(&src) {
        let lat: f64 = caps[1].parse().ok()?;
        let lng: f64 = caps[2].parse().ok()?;
        return Some(vec![lat, lng]);
    }
    None
}

/// Detecta si un precio_raw es "a consultar".
fn helper_es_consultable(raw: String) -> bool {
    let lower = raw.to_lowercase();
    lower.contains("consultar") || lower.contains("consulte")
}

/// Extrae monto USD de precio_raw.
fn helper_extraer_monto_usd(raw: String) -> Option<f64> {
    let re = Regex::new(r"(?i)(?:USD|U\$S|US\$)\s*([\d.,]+)").unwrap();
    re.captures(&raw)
        .and_then(|c| parse_numero_ar(c[1].to_string()))
}

/// Extrae monto en moneda local de precio_raw.
fn helper_extraer_monto_local(raw: String) -> Option<f64> {
    let re = Regex::new(r"^\$\s*([\d.,]+)").unwrap();
    re.captures(&raw)
        .and_then(|c| parse_numero_ar(c[1].to_string()))
}

/// Parsea número en formato argentino/boliviano.
fn parse_numero_ar(s: String) -> Option<f64> {
    let trimmed = s.trim();
    if trimmed.is_empty() {
        return None;
    }
    let has_dot = trimmed.contains('.');
    let has_comma = trimmed.contains(',');

    let normalized = if has_dot && has_comma {
        trimmed.replace('.', "").replace(',', ".")
    } else if has_dot {
        let dot_count = trimmed.matches('.').count();
        if dot_count > 1 {
            trimmed.replace('.', "")
        } else {
            let after_dot = trimmed.split('.').last().unwrap_or("");
            if after_dot.len() == 3 {
                trimmed.replace('.', "")
            } else {
                trimmed.to_string()
            }
        }
    } else if has_comma {
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

fn helper_parse_numero_ar(s: String) -> Option<f64> {
    parse_numero_ar(s)
}

// ── Evaluación de una regla Steel ────────────────────────────────────────────

/// Evalúa una regla .scm contra un dict de campos.
///
/// Cada regla se ejecuta en un Engine Steel aislado (sandbox):
/// 1. Crea Engine fresco
/// 2. Registra helpers Rust como funciones Scheme
/// 3. Carga el código .scm (define `aplicar`)
/// 4. Convierte campos JSON → hash Scheme
/// 5. Llama (aplicar campos)
/// 6. Convierte resultado → JSON
fn evaluar_regla(codigo: &str, campos: &serde_json::Value) -> Result<serde_json::Value, String> {
    use steel::steel_vm::engine::Engine;
    use steel::steel_vm::register_fn::RegisterFn;

    let mut vm = Engine::new();

    // Registrar helpers Rust en el namespace Scheme
    vm.register_fn("parse-leaflet-center", helper_parse_leaflet);
    vm.register_fn("parse-gmaps-coords", helper_parse_gmaps);
    vm.register_fn("es-consultable?", helper_es_consultable);
    vm.register_fn("extraer-monto-usd", helper_extraer_monto_usd);
    vm.register_fn("extraer-monto-local", helper_extraer_monto_local);
    vm.register_fn("parse-numero-ar", helper_parse_numero_ar);

    // Cargar la regla (define la función `aplicar`)
    // Steel's run() requires 'static lifetime, so we leak an owned copy.
    let codigo_owned: &'static str = Box::leak(codigo.to_string().into_boxed_str());
    vm.run(codigo_owned).map_err(|e| format!("Steel load: {e}"))?;

    // Convertir campos JSON → hash Scheme
    let steel_campos: steel::SteelVal = json_to_steel(campos)?;

    // Ejecutar (aplicar campos)
    let result = vm
        .call_function_by_name_with_args("aplicar", vec![steel_campos])
        .map_err(|e| format!("Steel eval: {e}"))?;

    // Convertir resultado → JSON
    steel_to_json(&result)
}

// ── MotorReglas ──────────────────────────────────────────────────────────────

/// Motor de reglas Steel/Scheme embebido en Rust, expuesto a Python via PyO3.
///
/// Evaluación granular:
/// - Cada regla se evalúa en un Engine Steel aislado (sandbox).
/// - Helpers Rust (regex, parsing numérico) se registran como funciones Scheme.
/// - Las reglas .scm son cortas y declarativas.
/// - Si una regla falla, se loggea y se continúa (degradación controlada).
#[pyclass]
pub struct MotorReglas {
    reglas: Vec<ReglaConfig>,
    codigos: HashMap<String, String>,
    reglas_toml_path: PathBuf,
    base_dir: PathBuf,
}

impl MotorReglas {
    pub fn new(reglas_toml_path: &str) -> Result<Self, String> {
        let path = PathBuf::from(reglas_toml_path);
        let base_dir = path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .to_path_buf();

        let mut motor = MotorReglas {
            reglas: Vec::new(),
            codigos: HashMap::new(),
            reglas_toml_path: path.clone(),
            base_dir,
        };

        if path.exists() {
            motor.cargar_reglas()?;
        }

        Ok(motor)
    }

    fn cargar_reglas(&mut self) -> Result<(), String> {
        let contenido = fs::read_to_string(&self.reglas_toml_path)
            .map_err(|e| format!("Error leyendo {}: {e}", self.reglas_toml_path.display()))?;

        let parsed: ReglasToml = toml::from_str(&contenido)
            .map_err(|e| format!("Error parseando TOML: {e}"))?;

        for regla in &parsed.regla {
            if !regla.activa {
                continue;
            }
            let archivo_path = self.base_dir.join(&regla.archivo);
            match fs::read_to_string(&archivo_path) {
                Ok(codigo) => {
                    self.codigos.insert(regla.nombre.clone(), codigo);
                }
                Err(e) => {
                    eprintln!(
                        "⚠ Regla '{}': no se pudo leer {}: {e}",
                        regla.nombre,
                        archivo_path.display()
                    );
                }
            }
        }

        self.reglas = parsed.regla;
        Ok(())
    }

    /// Evalúa las reglas que aplican a `fuente` sobre `campos`.
    ///
    /// Cada regla se evalúa en un Engine Steel aislado con helpers Rust.
    /// Si una regla falla, se loggea el error y se continúa.
    pub fn aplicar(
        &self,
        mut campos: serde_json::Value,
        fuente: &str,
    ) -> Result<serde_json::Value, String> {
        let reglas_aplicables = self.reglas_para_fuente(fuente);

        let mut reglas_aplicadas: Vec<String> = campos
            .get("reglas_aplicadas")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();

        for regla in &reglas_aplicables {
            if let Some(codigo) = self.codigos.get(&regla.nombre) {
                match evaluar_regla(codigo, &campos) {
                    Ok(resultado) => {
                        campos = resultado;
                        reglas_aplicadas.push(regla.nombre.clone());
                    }
                    Err(e) => {
                        eprintln!(
                            "⚠ Regla '{}': error evaluando Steel: {}",
                            regla.nombre, e
                        );
                    }
                }
            }
        }

        if let Some(obj) = campos.as_object_mut() {
            obj.insert(
                "reglas_aplicadas".to_string(),
                serde_json::json!(reglas_aplicadas),
            );
        }

        Ok(campos)
    }

    pub fn tiene_regla(&self, campo: &str, fuente: &str) -> bool {
        self.reglas.iter().any(|r| {
            r.activa
                && r.nombre.contains(campo)
                && (r.fuente.is_none() || r.fuente.as_deref() == Some(fuente))
        })
    }

    pub fn agregar_regla(
        &mut self,
        nombre: &str,
        codigo_scheme: &str,
        fuente: Option<&str>,
        confianza: f64,
    ) -> Result<(), String> {
        let subdir = match fuente {
            Some(f) => format!("sitios/{f}"),
            None => "base".to_string(),
        };
        let dir_path = self.base_dir.join(&subdir);
        fs::create_dir_all(&dir_path)
            .map_err(|e| format!("Error creando directorio {}: {e}", dir_path.display()))?;

        let archivo_nombre = format!("{nombre}.scm");
        let archivo_rel = format!("{subdir}/{archivo_nombre}");
        let archivo_path = self.base_dir.join(&archivo_rel);

        fs::write(&archivo_path, codigo_scheme)
            .map_err(|e| format!("Error escribiendo {}: {e}", archivo_path.display()))?;

        let nueva = ReglaConfig {
            nombre: nombre.to_string(),
            archivo: archivo_rel,
            fuente: fuente.map(String::from),
            activa: true,
            confianza,
        };

        self.codigos
            .insert(nombre.to_string(), codigo_scheme.to_string());
        self.reglas.push(nueva);

        self.persistir_toml()
    }

    fn persistir_toml(&self) -> Result<(), String> {
        let toml_data = ReglasToml {
            regla: self.reglas.clone(),
        };
        let contenido = toml::to_string_pretty(&toml_data)
            .map_err(|e| format!("Error serializando TOML: {e}"))?;
        fs::write(&self.reglas_toml_path, contenido)
            .map_err(|e| format!("Error escribiendo TOML: {e}"))?;
        Ok(())
    }

    fn reglas_para_fuente(&self, fuente: &str) -> Vec<&ReglaConfig> {
        self.reglas
            .iter()
            .filter(|r| {
                r.activa && (r.fuente.is_none() || r.fuente.as_deref() == Some(fuente))
            })
            .collect()
    }
}
