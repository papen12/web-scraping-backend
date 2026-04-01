;;; gmaps.scm — Extraer lat/lng de URL de iframe Google Maps.
;;;
;;; Campo de entrada: "iframe_src"
;;; Formatos soportados:
;;;   - !2d{lng}!3d{lat}  (maps/embed)
;;;   - q={lat},{lng}      (maps?q=)
;;; Resultado: lat, lng, geo_confianza="iframe"

(define (aplicar campos)
  (let ((src (hash-ref campos "iframe_src")))
    (if src
      (cond
        ;; Formato embed: !2d{lng}!3d{lat}
        ((string-contains src "!2d")
         (let* ((lng-start (+ (string-index-of src "!2d") 3))
                (lng-end   (string-index-of src "!" lng-start))
                (lat-start (+ (string-index-of src "!3d") 3))
                (lat-end   (or (string-index-of src "!" lat-start)
                               (string-length src)))
                (lng (string->number (substring src lng-start lng-end)))
                (lat (string->number (substring src lat-start lat-end))))
           (if (and lat lng)
             (let ((result (hash-set campos "lat" lat)))
               (let ((result (hash-set result "lng" lng)))
                 (hash-set result "geo_confianza" "iframe")))
             campos)))
        ;; Formato query: q={lat},{lng}
        ((string-contains src "q=")
         (let* ((q-start (+ (string-index-of src "q=") 2))
                (q-end   (or (string-index-of src "&" q-start)
                             (string-length src)))
                (q-val   (substring src q-start q-end))
                (parts   (string-split q-val ","))
                (lat (string->number (list-ref parts 0)))
                (lng (string->number (list-ref parts 1))))
           (if (and lat lng)
             (let ((result (hash-set campos "lat" lat)))
               (let ((result (hash-set result "lng" lng)))
                 (hash-set result "geo_confianza" "iframe")))
             campos)))
        (else campos))
      campos)))
