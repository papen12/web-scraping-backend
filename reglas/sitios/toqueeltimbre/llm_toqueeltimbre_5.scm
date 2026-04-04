(define (aplicar campos)
  (let ((valor (hash-try-get campos "latitud")))
    (if valor
      (hash-insert campos "lat" (string->number valor))
      campos)))