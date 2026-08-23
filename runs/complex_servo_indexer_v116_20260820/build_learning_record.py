from __future__ import annotations
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "learning" / "complex-servo-indexer-normality-bootstrap"
LOCKS = {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True}

def write(relative: str, text: str) -> str:
    path = BASE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path.relative_to(ROOT).as_posix()

def entry(relative: str) -> dict:
    path = ROOT / relative
    raw = path.read_bytes()
    return {"path": relative, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

def build() -> None:
    repro = write("repro/missing-origin-bootstrap.txt", "Run aicad_normality_prover.py against the original SIFC normality plan whose excludedEntityIds array was empty and whose first plan entity was ENV_BOTTOM. The plan_geometry gate fails even though ID, layer, endpoint, metadata, anchor and dimension evidence rows all pass, because the prover contract also requires the first plan entity to be an excluded global-origin bootstrap.\n")
    red = write("evidence/red-plan-geometry.txt", '{"status":"failed","failedGates":["plan_geometry"],"evidence":{"mappingErrors":[],"actualLayerCounts":{"OUTLINE":4},"expectedLayerCounts":{"OUTLINE":4},"failedEntities":[]},"hiddenFailedPredicate":"plan.entities[0].id in excluded"}\n')
    green = write("evidence/green-plan-geometry.txt", '{"status":"pass","failedGates":[],"correction":"ORIGIN_BOOTSTRAP is first, anchored at [0,0], and listed in excludedEntityIds"}\n')
    affected = write("affected/normality-bootstrap-contract.txt", "The corrected normality plan begins with an explicit ORIGIN_BOOTSTRAP line from the global origin, and the template excludes only that entity from production geometry. Production IDs, layer counts and feature topology remain unchanged.\n")
    report = {
        "schema": "aicad_test_failure_report_v1",
        "reportId": "REPORT-SIFC-NORMALITY-BOOTSTRAP-001",
        "status": "failed",
        "failedChecks": [{
            "failureId": "FAIL-SIFC-NORMALITY-ORIGIN-BOOTSTRAP",
            "failureAlias": "mechanical.normality_origin_bootstrap_missing_from_excluded_profile",
            "domain": "mechanical",
            "failingCheck": "aicad_normality_prover plan_geometry hard gate",
            "symptom": "The plan_geometry gate failed while its printed mapping, layer, endpoint, metadata, anchor and dimension evidence were all green.",
            "rootCause": "The run-specific plan omitted the prover's additional contract that the first plan entity must be an excluded line anchored at the global origin.",
            "correction": "Add ORIGIN_BOOTSTRAP as the first origin-anchored plan line and list it in excludedEntityIds without adding it to logical production geometry.",
            "candidateRule": {
                "id": "MECH-G035",
                "requirement": "A bounded mechanical normality plan must begin with one explicit excluded global-origin bootstrap before production entities.",
                "prevention": "Generate and validate the origin bootstrap and excludedEntityIds membership together, then assert the plan_geometry predicate before invoking the full prover.",
                "regressionTest": "A fixture with correct production bijection but no excluded origin bootstrap must fail plan_geometry; adding exactly one first origin bootstrap must pass without changing production IDs.",
                "safetyLocks": dict(LOCKS),
            },
            "reproducer": entry(repro),
            "evidenceClosure": {"policy": "exact_declared_evidence", "entries": [entry(red), entry(green)]},
            "sourceInputClosure": {"policy": "exact_declared_inputs", "entries": [
                entry("runs/complex_servo_indexer_v116_20260820/build_governance.py"),
                entry("agent-plugin/aicad-agent/scripts/aicad_normality_prover.py"),
            ]},
            "affectedArtifactClosure": {"policy": "exact_declared_artifacts", "entries": [
                entry(affected),
                entry("runs/complex_servo_indexer_v116_20260820/normality.plan.json"),
                entry("runs/complex_servo_indexer_v116_20260820/normality.template.json"),
                entry("runs/complex_servo_indexer_v116_20260820/normality.report.json"),
            ]},
        }],
        "safetyLocks": dict(LOCKS),
    }
    target = BASE / "reports" / "failures.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

if __name__ == "__main__": build()
