; Protocol v2, radial entity, and natural-language bridge test.
(vl-load-com)

(defun aicad-v2:emit (stream text)
  (write-line text stream)
  (princ (strcat "\n" text))
)

(defun aicad-v2:count (kind)
  (setq aicad-v2:ss (ssget "_X" (list (cons 0 kind) (cons 8 aicad:*layer*))))
  (if aicad-v2:ss (sslength aicad-v2:ss) 0)
)

(defun aicad-v2:write-bad-plan (filename / stream)
  (setq stream (open filename "w"))
  (write-line "AICAD|2|MM|0.000001|badproof" stream)
  (write-line "LINE|B001|0|0|10|0|purpose|reason|0|0|5|0" stream)
  (write-line "END|1|badproof" stream)
  (close stream)
)

(defun aicad-v2:run (/ root plugin report stream ok arc-result arc-ss arc-data xdata payload strings
                           job request-file result-file request-stream arguments exit-code result draw-result
                           circle-ss circle-data bad-file bad-result)
  (setq root (vl-string-translate "\\" "/" (getenv "AICAD_TEST_ROOT"))
        plugin (strcat root "/AiCadConstraint.lsp") report (strcat root "/v2-report.txt")
        stream (open report "w") ok T)
  (setvar "FILEDIA" 0)
  (command "_.ERASE" "_ALL" "")
  (aicad-v2:emit stream "AICAD_V2_BEGIN")
  (if (not (load plugin nil))
    (progn (aicad-v2:emit stream "FAIL:PLUGIN_LOAD") (setq ok nil))
    (aicad-v2:emit stream "PASS:PLUGIN_LOAD"))

  (if ok
    (progn
      (setq arc-result (aicad:draw-file (strcat root "/arc.aicad")))
      (if (not (car arc-result))
        (progn (aicad-v2:emit stream (strcat "FAIL:ARC_DRAW=" (cadr arc-result))) (setq ok nil))
        (progn
          (setq arc-ss (ssget "_X" (list '(0 . "ARC") (cons 8 aicad:*layer*))))
          (if (or (not arc-ss) (/= (sslength arc-ss) 1))
            (progn (aicad-v2:emit stream "FAIL:ARC_COUNT") (setq ok nil))
            (progn
              (setq arc-data (entget (ssname arc-ss 0) (list aicad:*regapp*))
                    xdata (assoc -3 arc-data) payload (if xdata (cdr (cadr xdata)) nil)
                    strings (if payload (vl-remove-if-not '(lambda (item) (= (car item) 1000)) payload) nil))
              (if (not (and (equal (cdr (assoc 40 arc-data)) 25.0 0.000001)
                            (equal (cdr (assoc 50 arc-data)) 0.0 0.000001)
                            (equal (cdr (assoc 51 arc-data)) (/ pi 2.0) 0.000001)
                            (= (cdr (nth 0 strings)) "A001") (= (cdr (nth 1 strings)) "ARC")))
                (progn (aicad-v2:emit stream "FAIL:ARC_GEOMETRY_OR_XDATA") (setq ok nil))
                (aicad-v2:emit stream "PASS:ARC_GEOMETRY_AND_XDATA"))))))))

  (if ok
    (progn
      (setq job (strcat root "/natural-job"))
      (if (not (vl-file-directory-p job)) (vl-mkdir job))
      (setq request-file (strcat job "/request.txt") result-file (strcat job "/result.txt")
            request-stream (open request-file "w" "utf8"))
      (write-line "120x80 plate with centered diameter 20 hole" request-stream)
      (close request-stream)
      (setq arguments (strcat "natural " (aicad:quote request-file) " --out " (aicad:quote job)
                              " --name drawing --provider offline --result " (aicad:quote result-file))
            exit-code (aicad:run arguments nil T) result (aicad:read-result result-file))
      (if (not (and (= exit-code 0) result (= (car result) "OK") (= (nth 2 result) "offline") (= (atoi (nth 3 result)) 5)))
        (progn (aicad-v2:emit stream "FAIL:NATURAL_BRIDGE") (setq ok nil))
        (progn
          (setq draw-result (aicad:draw-file (cadr result)))
          (if (not (car draw-result))
            (progn (aicad-v2:emit stream (strcat "FAIL:NATURAL_DRAW=" (cadr draw-result))) (setq ok nil))
            (progn
              (setq circle-ss (ssget "_X" (list '(0 . "CIRCLE") (cons 8 aicad:*layer*))))
              (if (or (not circle-ss) (/= (sslength circle-ss) 1))
                (progn (aicad-v2:emit stream "FAIL:CIRCLE_COUNT") (setq ok nil))
                (progn
                  (setq circle-data (entget (ssname circle-ss 0)))
                  (if (not (and (equal (car (cdr (assoc 10 circle-data))) 60.0 0.000001)
                                (equal (cadr (cdr (assoc 10 circle-data))) 40.0 0.000001)
                                (equal (cdr (assoc 40 circle-data)) 10.0 0.000001)
                                (= (aicad-v2:count "LINE") 4)))
                    (progn (aicad-v2:emit stream "FAIL:NATURAL_GEOMETRY") (setq ok nil))
                    (aicad-v2:emit stream "PASS:NATURAL_BRIDGE_AND_GEOMETRY"))))))))))

  (if ok
    (progn
      (setq bad-file (strcat root "/bad-proof.aicad"))
      (aicad-v2:write-bad-plan bad-file)
      (setq bad-result (aicad:validate-file bad-file))
      (if (car bad-result)
        (progn (aicad-v2:emit stream "FAIL:BAD_PROOF_ACCEPTED") (setq ok nil))
        (aicad-v2:emit stream "PASS:BAD_PROOF_REJECTED"))))

  (aicad-v2:emit stream (if ok "AICAD_V2_PASS" "AICAD_V2_FAIL"))
  (close stream)
  ok
)
