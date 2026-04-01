;;; precio.scm — Normalizar precio_raw a precio_usd y/o precio_local.
;;;
;;; Campo de entrada: "precio_raw"
;;; Casos:
;;;   "USD 150.000" o "U$S 150,000" → precio_usd=150000.0
;;;   "$ 50.000.000" → precio_local=50000000.0, moneda_local="ARS"
;;;   "Consultar" o "A consultar" → precio_consultable=#t
;;;   Números con puntos como separador de miles (formato AR/BO)

(define (aplicar campos)
  (let ((raw (hash-ref campos "precio_raw")))
    (if raw
      (let ((trimmed (string-trim raw)))
        (cond
          ;; Caso "Consultar" / "A consultar"
          ((or (string-contains-ci trimmed "consultar")
               (string-contains-ci trimmed "consulte"))
           (hash-set campos "precio_consultable" #t))

          ;; Caso USD: "USD 150.000", "U$S 150,000", "US$ 150.000"
          ((or (string-prefix-ci? "usd" trimmed)
               (string-prefix-ci? "u$s" trimmed)
               (string-prefix-ci? "us$" trimmed))
           (let* ((num-str (string-trim
                            (regexp-replace "^(?i)(usd|u\\$s|us\\$)\\s*" trimmed "")))
                  (num (parse-numero-ar num-str)))
             (if num
               (hash-set campos "precio_usd" num)
               campos)))

          ;; Caso moneda local: "$ 50.000.000"
          ((string-prefix? "$" trimmed)
           (let* ((num-str (string-trim (substring trimmed 1)))
                  (num (parse-numero-ar num-str)))
             (if num
               (let ((result (hash-set campos "precio_local" num)))
                 (hash-set result "moneda_local" "ARS"))
               campos)))

          ;; No se reconoce el formato
          (else campos)))
      campos)))

;;; Parsear número en formato argentino/boliviano.
;;; Puntos como separador de miles, coma como decimal.
(define (parse-numero-ar s)
  (let* ((sin-puntos (string-replace s "." ""))
         (normalizado (string-replace sin-puntos "," ".")))
    (string->number normalizado)))
