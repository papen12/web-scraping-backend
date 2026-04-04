(define (aplicar campos)
  (let ((valor (hash-try-get campos "precio_usd")))
    (if valor
      (hash-insert campos "precio_usd" (string->number valor))
      campos)))