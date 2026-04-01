mod extractor;
mod motor;

use pyo3::prelude::*;
use pyo3::types::PyDict;

pub use extractor::Extractor;
pub use motor::MotorReglas;

// ── PyO3 module ──────────────────────────────────────────────────────────────

#[pymodule]
fn _scraper_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<MotorReglas>()?;
    m.add_class::<Extractor>()?;
    Ok(())
}

// ── Extractor wrapper ────────────────────────────────────────────────────────

#[pymethods]
impl Extractor {
    #[new]
    pub fn py_new() -> Self {
        Extractor::new()
    }

    /// Extraer coordenadas de Leaflet JS state.
    /// Recibe el valor de `L.map.getCenter()` serializado como "lat,lng".
    #[pyo3(name = "extraer_leaflet")]
    pub fn py_extraer_leaflet(&self, js_center: &str) -> PyResult<(f64, f64)> {
        self.extraer_leaflet(js_center)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
    }

    /// Extraer coordenadas de un src de iframe de Google Maps.
    #[pyo3(name = "extraer_gmaps")]
    pub fn py_extraer_gmaps(&self, iframe_src: &str) -> PyResult<(f64, f64)> {
        self.extraer_gmaps(iframe_src)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
    }

    /// Normalizar un string de precio crudo.
    /// Devuelve dict con precio_usd, precio_local, moneda_local, precio_consultable.
    #[pyo3(name = "normalizar_precio")]
    pub fn py_normalizar_precio<'py>(
        &self,
        py: Python<'py>,
        precio_raw: &str,
    ) -> PyResult<Bound<'py, PyDict>> {
        let result = self.normalizar_precio(precio_raw);
        let dict = PyDict::new_bound(py);
        dict.set_item("precio_usd", result.precio_usd)?;
        dict.set_item("precio_local", result.precio_local)?;
        dict.set_item("moneda_local", result.moneda_local.as_deref())?;
        dict.set_item("precio_consultable", result.precio_consultable)?;
        Ok(dict)
    }
}

// ── MotorReglas wrapper ──────────────────────────────────────────────────────

#[pymethods]
impl MotorReglas {
    #[new]
    #[pyo3(signature = (reglas_toml_path = "reglas/reglas.toml"))]
    pub fn py_new(reglas_toml_path: &str) -> PyResult<Self> {
        MotorReglas::new(reglas_toml_path)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }

    /// Evalúa las reglas que aplican a `fuente` sobre `campos`.
    /// Devuelve un dict actualizado con los campos transformados.
    #[pyo3(name = "aplicar")]
    pub fn py_aplicar<'py>(
        &self,
        py: Python<'py>,
        campos: &Bound<'py, PyDict>,
        fuente: &str,
    ) -> PyResult<Bound<'py, PyDict>> {
        // Convertir PyDict → serde_json::Value
        let json_str: String = py
            .import_bound("json")?
            .call_method1("dumps", (campos,))?
            .extract()?;
        let value: serde_json::Value =
            serde_json::from_str(&json_str).map_err(|e| {
                pyo3::exceptions::PyValueError::new_err(format!("JSON inválido: {e}"))
            })?;

        let result = self.aplicar(value, fuente).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(e)
        })?;

        // Convertir serde_json::Value → PyDict
        let result_str = serde_json::to_string(&result).unwrap();
        let json_mod = py.import_bound("json")?;
        let py_obj = json_mod.call_method1("loads", (result_str,))?;
        Ok(py_obj.downcast_into::<PyDict>().map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Error convirtiendo resultado: {e}"))
        })?)
    }

    /// Verifica si existe una regla activa para un campo y fuente dados.
    #[pyo3(name = "tiene_regla")]
    pub fn py_tiene_regla(&self, campo: &str, fuente: &str) -> bool {
        self.tiene_regla(campo, fuente)
    }

    /// Agrega una nueva regla en memoria y la persiste en el archivo TOML.
    #[pyo3(name = "agregar_regla")]
    #[pyo3(signature = (nombre, codigo_scheme, fuente=None, confianza=0.5))]
    pub fn py_agregar_regla(
        &mut self,
        nombre: &str,
        codigo_scheme: &str,
        fuente: Option<&str>,
        confianza: f64,
    ) -> PyResult<()> {
        self.agregar_regla(nombre, codigo_scheme, fuente, confianza)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }
}