(define (aplicar campos)
  (let ((geo_confianza_raw (hash-try-get campos "geo_confianza_raw")))
    (if geo_confianza_raw
      (hash-insert campos "geo_confianza" geo_confianza_raw)
      campos)))