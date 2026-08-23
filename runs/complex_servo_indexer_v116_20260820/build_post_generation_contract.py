from __future__ import annotations

import hashlib
import json
from pathlib import Path


RUN = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(artifact_id: str, kind: str, relative: str) -> dict[str, str]:
    path = RUN / relative
    return {
        "artifactId": artifact_id,
        "partId": "SIFC-220-REV-A",
        "kind": kind,
        "path": relative.replace("\\", "/"),
        "revision": "A",
        "sha256": sha256(path),
    }


def build() -> None:
    evidence_dir = RUN / "post_generation_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    candidates = [
        artifact("sifc-220-native-cad", "native_cad", "model3d_native_r2/SIFC_220_REV_A.SLDPRT"),
        artifact("sifc-220-neutral-step", "neutral_step", "model3d_native_r2/SIFC_220_REV_A.step"),
        artifact("sifc-220-controlled-drawing", "manufacturing_drawing", "drawing2d_final/SIFC_220_REV_A_DRAWING.dxf"),
    ]
    evidence = {
        "schema": "aicad_review_only_post_generation_evidence_v1",
        "artifactSha256ById": {row["artifactId"]: row["sha256"] for row in candidates},
        "intent": {"wholeIntent": True},
        "design": {"constraintCompile": True},
        "definition": {"materialDesignationPresent": True},
        "verification": {
            "drawingCompleteness": False,
            "reason": "Controlled review drawing exists, but full manufacturing GD&T, roughness coverage, licensed approval and release evidence are intentionally absent.",
        },
        "host": {
            "nativeCadSaveReopenByArtifactId": {"sifc-220-native-cad": True},
            "nativeSourceSaveHashMatchesArtifact": True,
        },
        "release": {
            "manufacturingReviewRecorded": False,
            "reviewerIdentityPresent": False,
            "recordedApprovalSignaturePresent": False,
        },
        "readinessBoundary": {
            "technicalPackageReady": False,
            "productionReleaseEligible": False,
            "manufacturingAuthorized": False,
        },
    }
    evidence_path = evidence_dir / "review-only-evidence.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence_ref = {
        "path": "post_generation_evidence/review-only-evidence.json",
        "sha256": sha256(evidence_path),
    }

    def gate(kind: str, notes: str) -> dict[str, object]:
        return {"evidenceRef": {"kind": kind, **evidence_ref}, "notes": notes}

    contract = {
        "schema": "aicad_production_readiness_contract_v3",
        "project": {"id": "SIFC-220-REV-A", "title": "High-stiffness servo indexer flange cartridge"},
        "requestedStage": "manufacturing",
        "discipline": "mechanical",
        "strictProductionOnly": True,
        "evidence": {
            "intent": {"wholeIntent": gate("authority_document", "Review intent is recorded; manufacturing authority is not claimed.")},
            "design": {"constraintCompile": gate("machine_report", "2D and 3D constrained plans compiled successfully.")},
            "manufacturingDefinition": {"materialDesignation": gate("machine_report", "7075-T651 is declared, without full process authority.")},
            "verification": {"drawingCompleteness": gate("machine_report", "Deliberately false until full manufacturing definition and licensed review exist.")},
            "host": {"nativeCadSaveReopen": gate("native_host_report", "SolidWorks native save/reopen is hash-bound; other host gates remain absent.")},
            "release": {"manufacturingReviewRecorded": gate("review_release", "Deliberately false; no manufacturing approval or signature is asserted.")},
        },
        "artifactSubjects": [{"partId": "SIFC-220-REV-A", "subjectType": "manufactured_part", "revision": "A"}],
        "expectedArtifactClosure": [
            {key: value for key, value in row.items() if key != "sha256"}
            for row in candidates
        ],
        "candidateArtifacts": candidates,
        "safetyLocks": {
            "reviewOnly": True,
            "accepted": False,
            "ruleEnabled": False,
            "packagingGated": True,
            "comparativeSuperiorityClaimAllowed": False,
        },
    }
    (RUN / "production-readiness-contract-v3.review-only.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    build()
