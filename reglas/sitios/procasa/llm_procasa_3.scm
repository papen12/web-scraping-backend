(define (aplicar campos)
  (let ((precio_raw (hash-try-get campos "precio_raw")))
    (if precio_raw
      (hash-insert campos "precio_consultable" (if (string=? precio_raw "a consultar") #t #f))
      campos)))