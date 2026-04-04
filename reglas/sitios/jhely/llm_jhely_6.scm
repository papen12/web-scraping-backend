(define (aplicar campos)
  (let ((geo_confianza_raw (hash-try-get campos "geo_confianza_raw")))
    (if geo_confianza_raw
      (hash-insert campos "geo_confianza" "leaflet")
      (hash-insert campos "geo_confianza" "ausente"))))