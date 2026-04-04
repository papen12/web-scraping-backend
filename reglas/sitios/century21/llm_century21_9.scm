(define (aplicar campos)
  (let ((precio_local_raw (hash-try-get campos "precio_local_raw")))
    (if precio_local_raw
      (hash-insert campos "precio_local" (string->number precio_local_raw))
      campos)))