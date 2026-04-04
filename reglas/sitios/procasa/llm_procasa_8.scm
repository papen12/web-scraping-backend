(define (aplicar campos)
  (let ((precio_usd_raw (hash-try-get campos "precio_usd_raw")))
    (if precio_usd_raw
      (hash-insert campos "precio_usd" (string->number precio_usd_raw))
      campos)))