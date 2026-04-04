(define (aplicar campos)
  (let ((valor (hash-try-get campos "precio_raw")))
    (if valor
      (hash-insert campos "precio_consultable" #f)
      (hash-insert campos "precio_consultable" #t))))