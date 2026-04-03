;;; leaflet.scm — Extraer lat/lng del estado interno de Leaflet.
;;;
;;; Campo de entrada: "js_leaflet_center" con valor "{lat},{lng}"
;;; Helper Rust: (parse-leaflet-center str) → lista (lat lng) o #f
;;; Resultado: lat, lng, geo_confianza="leaflet"

(define (aplicar campos)
  (let ((center (hash-try-get campos "js_leaflet_center")))
    (if center
      (let ((coords (parse-leaflet-center center)))
        (if coords
          (hash-insert
            (hash-insert
              (hash-insert campos "lat" (car coords))
              "lng" (car (cdr coords)))
            "geo_confianza" "leaflet")
          campos))
      campos)))
