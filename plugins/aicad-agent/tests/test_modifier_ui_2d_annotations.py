from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime" if (ROOT / "runtime" / "src").is_dir() else ROOT.parents[1]
sys.path.insert(0, str(SOURCE / "src"))

from aicad.viewmap import generate_view_package, render_review_html, validate_review_html


class ModifierUi2dAnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads((SOURCE / "schema" / "aicad-view-package.schema.json").read_text(encoding="utf-8"))

    def _single_storey_package(self) -> dict:
        plan = json.loads((SOURCE / "examples" / "protocol3-text-layer.plan.json").read_text(encoding="utf-8"))
        package = generate_view_package(plan, "2d", "architecture")
        view = package["views"][0]
        view["storey_id"] = "LF"
        view["document_id"] = "DOC_LF"
        for entity in view["entities"]:
            entity["storey_id"] = "LF"
            entity["document_id"] = "DOC_LF"
        for ref in package["selection_map"].values():
            ref["storey_id"] = "LF"
            ref["document_id"] = "DOC_LF"
            ref["reference_key"] = f"LF|{ref['source_object_id']}|{ref['source_subobject']}"
        package["document_set"] = {
            "drawing_set_mode": "multi_storey",
            "requested_storey_ids": ["LF"],
            "default_storey_id": "LF",
            "active_storey_id": "LF",
            "document_set_sha256": "a" * 64,
            "modifier_mode": "document_set_switcher",
            "selection_scope_mode": "document_scoped",
            "documents": [{"storey_id": "LF"}],
            "storeys": [{"id": "LF", "label": "下层"}],
        }
        return package

    def test_native_text_is_upright_selectable_unicode_and_not_inferred_from_purpose(self) -> None:
        plan = json.loads((SOURCE / "examples" / "protocol3-text-layer.plan.json").read_text(encoding="utf-8"))
        package = generate_view_package(plan, "2d", "architecture")
        Draft202012Validator(self.schema).validate(package)
        axis_text = "\u8f741"
        text_entity = next(entity for entity in package["views"][0]["entities"] if entity["source_object_id"] == "AX1T")
        self.assertEqual(text_entity["geometry"]["display"], {
            "kind": "text", "value": axis_text, "height": 80.0, "rotation_deg": 0.0,
        })
        page = render_review_html(package)
        expected_text_count = sum(
            entity["geometry"].get("display", {}).get("kind") == "text"
            for view in package["views"] for entity in view["entities"]
        )
        self.assertEqual(page.count('<text class="native-text '), expected_text_count)
        self.assertEqual(validate_review_html(page, "2d"), [])
        self.assertIn('<text class="native-text role-annotation layer-grid-text"', page)
        self.assertIn(f'dominant-baseline="central">{axis_text}</text>', page)
        self.assertIn('class="view-hit text-hit"', page)
        self.assertIn('data-view-entity-id="PLAN_AX1T"', page)
        self.assertNotIn("axis-bubble-label", page)
        for marker in ("\ufffd", "\u951f", "\u70eb\u70eb", "\u5c6f\u5c6f"):
            self.assertNotIn(marker, page)

    def test_dimension_has_model_measurement_label_and_two_endpoint_ticks(self) -> None:
        plan = json.loads((SOURCE / "examples" / "architecture-dimensions.plan.json").read_text(encoding="utf-8"))
        package = generate_view_package(plan, "2d", "architecture")
        Draft202012Validator(self.schema).validate(package)
        dimension = next(entity for entity in package["views"][0]["entities"] if entity["id"] == "PLAN_D_OVERALL_X_D")
        self.assertEqual(dimension["geometry"]["display"]["kind"], "dimension")
        self.assertEqual(dimension["geometry"]["display"]["measurement"], 1000.0)
        page = render_review_html(package)
        expected_dimension_count = sum(
            entity["geometry"].get("display", {}).get("kind") == "dimension"
            for view in package["views"] for entity in view["entities"]
        )
        self.assertEqual(page.count('<text class="dimension-value '), expected_dimension_count)
        self.assertEqual(page.count('class="dimension-tick"'), expected_dimension_count * 2)
        self.assertIn('<text class="dimension-value layer-dimension"', page)
        self.assertIn(f'aria-label="{chr(0x5c3a)}{chr(0x5bf8)} 1000 mm">1000</text>', page)

    def test_document_set_storey_switcher_is_optional_and_clears_namespaced_selection(self) -> None:
        plan = json.loads((SOURCE / "examples" / "protocol3-text-layer.plan.json").read_text(encoding="utf-8"))
        package = generate_view_package(plan, "2d", "architecture")
        plain_page = render_review_html(package)
        self.assertNotIn('id="storeySwitcher"', plain_page)

        base_view = package["views"][0]
        views = []
        selection_map = {}
        for storey_id in ("LF", "MF", "UF"):
            view = copy.deepcopy(base_view)
            view["id"] = f"{storey_id}_PLAN"
            view["label"] = f"{storey_id} \u5c42\u5e73\u9762"
            view["storey_id"] = storey_id
            view["document_id"] = f"DOC_{storey_id}"
            for entity in view["entities"]:
                old_id = entity["id"]
                entity["id"] = f"{storey_id}_{old_id}"
                entity["view_id"] = view["id"]
                entity["storey_id"] = storey_id
                entity["document_id"] = f"DOC_{storey_id}"
                ref = copy.deepcopy(package["selection_map"][old_id])
                ref["view_id"] = view["id"]
                ref["view_entity_id"] = entity["id"]
                ref["reference_key"] = f"{storey_id}|{ref['source_object_id']}|{ref['source_subobject']}"
                selection_map[entity["id"]] = ref
                ref["storey_id"] = storey_id
                ref["document_id"] = f"DOC_{storey_id}"
            views.append(view)
        package["views"] = views
        package["selection_map"] = selection_map
        labels = {"LF": "\u4e0b\u5c42", "MF": "\u4e3b\u5c42", "UF": "\u4e0a\u5c42"}
        package["document_set"] = {
            "default_storey_id": "MF",
            "drawing_set_mode": "multi_storey",
            "requested_storey_ids": ["LF", "MF", "UF"],
            "active_storey_id": "MF",
            "modifier_mode": "document_set_switcher",
            "selection_scope_mode": "document_scoped",
            "documents": [{"storey_id": value} for value in ("LF", "MF", "UF")],
            "document_set_sha256": "a" * 64,
            "storeys": [{"id": storey_id, "label": label} for storey_id, label in labels.items()],
        }
        Draft202012Validator(self.schema).validate(package)
        page = render_review_html(package)
        self.assertEqual(validate_review_html(page, "2d"), [])
        self.assertIn('id="storeySwitcher" data-default-storey-id="MF"', page)
        for storey_id, label in labels.items():
            self.assertEqual(page.count(f'data-storey-id="{storey_id}"'), 1)
            self.assertEqual(page.count(f'data-view-storey-id="{storey_id}"'), 1)
            self.assertIn(f'>{label}</button>', page)
        self.assertIn('data-aicad-modifier-mode="document_set_switcher"', page)
        self.assertIn('data-artifact-role="interactive_drawing_modifier"', page)
        self.assertIn('data-selection-scope-mode="document_scoped"', page)
        self.assertIn('data-default-storey-id="MF" data-active-storey-id="MF"', page)
        self.assertIn(f'<meta name="aicad-document-set-sha256" content="{"a" * 64}">', page)
        self.assertIn('data-view-storey-id="LF" hidden', page)
        self.assertIn('data-view-storey-id="MF"><div', page)
        self.assertIn('data-view-storey-id="UF" hidden', page)
        axis_refs = [ref for ref in package["selection_map"].values() if ref["source_object_id"] == "AX1T"]
        self.assertEqual({ref["storey_id"] for ref in axis_refs}, set(labels))
        self.assertEqual(len({ref["reference_key"] for ref in axis_refs}), 3)
        self.assertIn("selectedRefs=[];selected=[];primeSelectedMeasurementEditor();renderUi();", page)
        self.assertIn("card.dataset.viewStoreyId!==id", page)
        self.assertIn("ref=pkg.selection_map[x.dataset.viewEntityId],key=ref?referenceKey(ref)", page)
        self.assertIn("document.elementsFromPoint(event.clientX,event.clientY)", page)
        self.assertNotIn("querySelectorAll('.view-hit').forEach(x=>x.onclick", page)
        self.assertIn("get activeStorey(){return activeStorey}", page)

    def test_document_set_fails_closed_for_incomplete_or_conflicting_scope(self) -> None:
        mutations = (
            "all_untagged", "mixed_untagged", "wrong_drawing_mode", "wrong_modifier_mode",
            "wrong_selection_scope", "missing_digest", "requested_mismatch",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                package = self._single_storey_package()
                if mutation == "all_untagged":
                    package["views"][0].pop("storey_id")
                elif mutation == "mixed_untagged":
                    extra = copy.deepcopy(package["views"][0])
                    extra["id"] = "UNTAGGED_PLAN"
                    extra.pop("storey_id")
                    package["views"].append(extra)
                elif mutation == "wrong_drawing_mode":
                    package["document_set"]["drawing_set_mode"] = "single_storey"
                elif mutation == "wrong_modifier_mode":
                    package["document_set"]["modifier_mode"] = "wrong"
                elif mutation == "wrong_selection_scope":
                    package["document_set"]["selection_scope_mode"] = "global"
                elif mutation == "missing_digest":
                    package["document_set"].pop("document_set_sha256")
                else:
                    package["document_set"]["requested_storey_ids"] = ["UF"]
                with self.assertRaises(ValueError):
                    render_review_html(package)

    def test_public_selection_entrypoint_rejects_cross_storey_injection(self) -> None:
        page = render_review_html(self._single_storey_package())
        script = page.split("function toggleSelectionRef(raw)", 1)[1].split("function scopeFields", 1)[0]
        guard = "if(activeStorey&&(r.storey_id!==activeStorey||!key.startsWith(`${activeStorey}|`)))"
        mutation = "const i=selectedRefs.findIndex"
        self.assertIn(guard, script)
        self.assertIn("showToast('\\u5f53\\u524d\\u697c\\u5c42", script)
        self.assertLess(script.index(guard), script.index(mutation))



if __name__ == "__main__":
    unittest.main()
