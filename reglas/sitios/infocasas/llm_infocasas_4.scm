(define (aplicar campos)
  (let ((moneda (hash-try-get campos "moneda")))
    (if moneda
      (hash-insert campos "moneda_local" moneda)
      campos)))