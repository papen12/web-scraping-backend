(define (aplicar campos)
  (let ((lat_raw (hash-try-get campos "lat_raw")))
    (if lat_raw
      (hash-insert campos "lat" (string->number lat_raw))
      campos)))