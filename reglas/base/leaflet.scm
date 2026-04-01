;;; leaflet.scm — Extraer lat/lng del estado interno de Leaflet.
;;;
;;; Campo de entrada: "js_leaflet_center" con valor "{lat},{lng}"
;;; Resultado: lat, lng, geo_confianza="leaflet"

(define (aplicar campos)
  (let ((center (hash-ref campos "js_leaflet_center")))
    (if center
      (let* ((parts (string-split center ","))
             (lat-str (string-trim (list-ref parts 0)))
             (lng-str (string-trim (list-ref parts 1)))
             (lat (string->number lat-str))
             (lng (string->number lng-str)))
        ;; Validar rangos
        (if (and lat lng
                 (>= lat -90) (<= lat 90)
                 (>= lng -180) (<= lng 180))
          (let ((result (hash-set campos "lat" lat)))
            (let ((result (hash-set result "lng" lng)))
              (hash-set result "geo_confianza" "leaflet")))
          campos))
      campos)))
