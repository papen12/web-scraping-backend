(define (aplicar campos)
  (let ((valor (hash-try-get campos "longitud")))
    (if valor
      (hash-insert campos "lng" valor)
      campos)))