;;; gmaps.scm — Extraer lat/lng de URL de iframe Google Maps.
;;;
;;; Campo de entrada: "iframe_src"
;;; Helper Rust: (parse-gmaps-coords str) → lista (lat lng) o #f
;;; Formatos soportados:
;;;   - !2d{lng}!3d{lat}  (maps/embed)
;;;   - q={lat},{lng}      (maps?q=)
;;; Resultado: lat, lng, geo_confianza="iframe"

(define (aplicar campos)
  (let ((src (hash-try-get campos "iframe_src")))
    (if src
      (let ((coords (parse-gmaps-coords src)))
        (if coords
          (hash-insert
            (hash-insert
              (hash-insert campos "lat" (car coords))
              "lng" (car (cdr coords)))
            "geo_confianza" "iframe")
          campos))
      campos)))
