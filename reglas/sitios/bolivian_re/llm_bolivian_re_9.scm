(define (aplicar campos)
  (if (hash-contains? campos "lat") 
    (hash-insert campos "geo_confianza" "leaflet")
    (hash-insert campos "geo_confianza" "ausente")))