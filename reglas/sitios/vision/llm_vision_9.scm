(define (aplicar campos)
  (let ((valor (hash-try-get campos "precio_local")))
    (if valor
      (hash-insert campos "precio_local" (string->number valor))
      campos)))