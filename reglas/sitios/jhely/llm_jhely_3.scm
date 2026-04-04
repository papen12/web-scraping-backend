(define (aplicar campos)
  (let ((precio_raw (hash-try-get campos "precio_raw")))
    (if precio_raw
      (hash-insert campos "precio_consultable" #f)
      (hash-insert campos "precio_consultable" #t))))