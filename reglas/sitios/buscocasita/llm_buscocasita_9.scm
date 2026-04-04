(define (aplicar campos)
  (let ((valor (hash-try-get campos "precio_local_raw")))
    (if valor
      (hash-insert campos "precio_local" valor)
      campos)))