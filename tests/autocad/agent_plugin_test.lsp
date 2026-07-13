; End-to-end check for an artifact generated through aicad-agent.
(vl-load-com)

(defun aicad-agent-test:emit (stream text)
  (write-line text stream)
  (princ (strcat "\n" text))
)

(defun aicad-agent-test:run (/ root plugin plan report stream result lines circles data center ok)
  (setq root (vl-string-translate "\\" "/" (getenv "AICAD_TEST_ROOT"))
        plugin (strcat root "/AiCadConstraint.lsp")
        plan (strcat root "/agent-plate.aicad")
        report (strcat root "/agent-plugin-report.txt")
        stream (open report "w") ok T)
  (setvar "FILEDIA" 0)
  (command "_.ERASE" "_ALL" "")
  (aicad-agent-test:emit stream "AICAD_AGENT_BEGIN")
  (if (not (load plugin nil))
    (progn (aicad-agent-test:emit stream "FAIL:PLUGIN_LOAD") (setq ok nil))
    (aicad-agent-test:emit stream "PASS:PLUGIN_LOAD"))
  (if ok
    (progn
      (setq result (aicad:draw-file plan))
      (if (not (and (car result) (= (cadr result) 5)))
        (progn (aicad-agent-test:emit stream "FAIL:DRAW_RESULT") (setq ok nil))
        (progn
          (setq lines (ssget "_X" (list '(0 . "LINE") (cons 8 aicad:*layer*)))
                circles (ssget "_X" (list '(0 . "CIRCLE") (cons 8 aicad:*layer*))))
          (if (not (and lines (= (sslength lines) 4) circles (= (sslength circles) 1)))
            (progn (aicad-agent-test:emit stream "FAIL:ENTITY_COUNTS") (setq ok nil))
            (progn
              (setq data (entget (ssname circles 0)) center (cdr (assoc 10 data)))
              (if (not (and (equal (car center) 60.0 0.000001)
                            (equal (cadr center) 40.0 0.000001)
                            (equal (cdr (assoc 40 data)) 10.0 0.000001)))
                (progn (aicad-agent-test:emit stream "FAIL:CIRCLE_GEOMETRY") (setq ok nil))
                (aicad-agent-test:emit stream "PASS:AGENT_ARTIFACT_GEOMETRY"))))))))
  (aicad-agent-test:emit stream (if ok "AICAD_AGENT_PASS" "AICAD_AGENT_FAIL"))
  (close stream)
  ok
)
