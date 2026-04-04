(define (aplicar campos)
  (let ((valor (hash-try-get campos "geo_confianza")))
    (if valor
      (hash-insert campos "geo_confianza" valor)
      (hash-insert campos "geo_confianza" "ausente"))))