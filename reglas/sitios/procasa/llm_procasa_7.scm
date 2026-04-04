(define (aplicar campos)
  (let ((lng_raw (hash-try-get campos "lng_raw")))
    (if lng_raw
      (hash-insert campos "lng" (string->number lng_raw))
      campos)))