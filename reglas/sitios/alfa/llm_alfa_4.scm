(define (aplicar campos)
  (let ((valor (hash-try-get campos "moneda")))
    (if valor
      (hash-insert campos "moneda_local" valor)
      campos)))