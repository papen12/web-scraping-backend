;;; precio.scm — Normalizar precio_raw a precio_usd y/o precio_local.
;;;
;;; Campo de entrada: "precio_raw"
;;; Helpers Rust:
;;;   (es-consultable? str) → bool
;;;   (extraer-monto-usd str) → float o #f
;;;   (extraer-monto-local str) → float o #f
;;; Casos:
;;;   "USD 150.000" o "U$S 150,000" → precio_usd=150000.0
;;;   "$ 50.000.000" → precio_local=50000000.0, moneda_local="ARS"
;;;   "Consultar" o "A consultar" → precio_consultable=#t

(define (aplicar campos)
  (let ((raw (hash-try-get campos "precio_raw")))
    (if raw
      (if (es-consultable? raw)
        (hash-insert campos "precio_consultable" #t)
        (let ((usd (extraer-monto-usd raw)))
          (if usd
            (hash-insert campos "precio_usd" usd)
            (let ((local (extraer-monto-local raw)))
              (if local
                (hash-insert
                  (hash-insert campos "precio_local" local)
                  "moneda_local" "ARS")
                campos)))))
      campos)))
