(define (aplicar campos)
  (let ((valor (hash-ref campos "lng")))
    (if valor
      (hash-set campos "lng" (string->number valor))
      (hash-set campos "lng" 0))))