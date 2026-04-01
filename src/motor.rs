use pyo3::prelude::*;
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

// ── MotorReglas ──────────────────────────────────────────────────────────────

/// Motor de reglas Steel/Scheme embebido en Rust, expuesto a Python via PyO3.
///
/// Carga reglas .scm definidas en un archivo TOML índice.
/// Cada regla define `(define (aplicar campos) ...)` que recibe y devuelve
/// un hash con los campos del esquema canónico.
#[pyclass]
pub struct MotorReglas {
    reglas: Vec<ReglaConfig>,
    codigos: HashMap<String, String>, // nombre → código Scheme
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

        // Si el archivo existe, cargar reglas
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
    /// Una regla aplica si:
    ///   - fuente de la regla es None (regla global), o
    ///   - fuente de la regla coincide con la fuente dada.
    ///
    /// **Nota:** La evaluación Steel real requiere que steel-core compile
    /// correctamente con el feature set actual. Este scaffold provee la
    /// estructura y el fallback para desarrollo.
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
            if let Some(_codigo) = self.codigos.get(&regla.nombre) {
                // ── Steel evaluation ──
                // En producción, aquí se invoca el intérprete Steel:
                //
                //   let mut vm = steel_core::steel_vm::engine::Engine::new();
                //   vm.run(&codigo)?;
                //   let result = vm.call_function_by_name_with_args(
                //       "aplicar",
                //       vec![campos_to_steel_value(&campos)],
                //   )?;
                //
                // Por ahora hacemos passthrough para que el scaffold compile
                // y los tests de integración Python funcionen.
                reglas_aplicadas.push(regla.nombre.clone());
            }
        }

        // Actualizar metadata
        if let Some(obj) = campos.as_object_mut() {
            obj.insert(
                "reglas_aplicadas".to_string(),
                serde_json::json!(reglas_aplicadas),
            );
        }

        Ok(campos)
    }

    /// Verifica si existe una regla activa para un campo/fuente dados.
    pub fn tiene_regla(&self, campo: &str, fuente: &str) -> bool {
        self.reglas.iter().any(|r| {
            r.activa
                && r.nombre.contains(campo)
                && (r.fuente.is_none() || r.fuente.as_deref() == Some(fuente))
        })
    }

    /// Agrega una nueva regla en memoria y la persiste en el archivo TOML.
    pub fn agregar_regla(
        &mut self,
        nombre: &str,
        codigo_scheme: &str,
        fuente: Option<&str>,
        confianza: f64,
    ) -> Result<(), String> {
        // Determinar directorio y archivo
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

        // Escribir archivo .scm
        fs::write(&archivo_path, codigo_scheme)
            .map_err(|e| format!("Error escribiendo {}: {e}", archivo_path.display()))?;

        // Agregar a memoria
        let nueva = ReglaConfig {
            nombre: nombre.to_string(),
            archivo: archivo_rel.clone(),
            fuente: fuente.map(String::from),
            activa: true,
            confianza,
        };

        self.codigos
            .insert(nombre.to_string(), codigo_scheme.to_string());
        self.reglas.push(nueva);

        // Persistir TOML
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
