(define (aplicar campos)
  (let ((geo (hash-try-get campos "geo")))
    (if geo
      (hash-insert campos "geo_confianza" "leaflet")
      (hash-insert campos "geo_confianza" "ausente"))))