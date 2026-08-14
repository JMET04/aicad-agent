from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_github_source.py"
SPEC = importlib.util.spec_from_file_location("aicad_verify_github_source", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)

RELEASE_SCRIPT = ROOT / "scripts" / "verify_release_package.py"
RELEASE_SPEC = importlib.util.spec_from_file_location("aicad_verify_release_package", RELEASE_SCRIPT)
assert RELEASE_SPEC is not None and RELEASE_SPEC.loader is not None
RELEASE_VERIFY = importlib.util.module_from_spec(RELEASE_SPEC)
RELEASE_SPEC.loader.exec_module(RELEASE_VERIFY)


class GitHubShowcaseVerifierTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        showcase = root / "showcase"
        showcase.mkdir()
        linked_paths: list[str] = []
        demos: list[dict] = []
        role_names = {
            "preview": "preview.png",
            "interactive_review": "review.html",
            "validation_machine": "validation.json",
            "validation_human": "validation.md",
            "source_manifest": "source-manifest.json",
        }
        input_locks = {
            "reviewOnly": True,
            "accepted": False,
            "ruleEnabled": False,
            "packagingGated": True,
        }
        for slug in VERIFY.SHOWCASE_SLUGS:
            target = showcase / slug
            target.mkdir()
            artifacts: list[dict] = []
            for role, name in role_names.items():
                path = target / name
                path.write_bytes(f"{slug}:{role}".encode())
                relative = path.relative_to(showcase).as_posix()
                linked_paths.append(relative)
                artifacts.append({"role": role, "path": relative})
            archive = target / f"{slug}-sanitized-review-candidate.zip"
            archive.write_bytes(f"{slug}:candidate".encode())
            archive_relative = archive.relative_to(showcase).as_posix()
            linked_paths.append(archive_relative)
            artifacts.append({
                "role": "sanitized_review_candidate",
                "path": archive_relative,
            })
            demos.append({
                "slug": slug,
                "inputSafetyLocks": dict(input_locks),
                "sourceManifestClosure": {"exactBidirectionalClosure": True},
                "artifacts": artifacts,
            })

        readme = showcase / "README.md"
        readme.write_text("\n".join(linked_paths) + "\n", encoding="utf-8")
        output_files = [
            {
                "path": path.relative_to(showcase).as_posix(),
                "size": path.stat().st_size,
                "sha256": VERIFY.sha256(path),
            }
            for path in sorted(
                (path for path in showcase.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(showcase).as_posix(),
            )
        ]
        manifest = {
            "schema": "aicad_github_showcase_v2",
            "releaseStatus": "engineering-review-candidate",
            "safetyLocks": {
                **input_locks,
                "productionOrFabricationAcceptanceClaimed": False,
            },
            "demos": demos,
            "outputClosure": {
                "policy": "all_output_files_except_manifest_self",
                "files": output_files,
            },
        }
        (showcase / "showcase-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return root

    def test_four_slug_links_locks_and_output_closure_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._fixture(Path(temporary))
            errors: list[str] = []
            self.assertGreater(VERIFY.verify_showcase(root, errors), 0)
            self.assertEqual([], errors)

    def test_slug_role_link_lock_and_output_closure_mutations_fail(self) -> None:
        mutations = (
            ("slug", "showcase-demo-bijection:"),
            ("role_link", "showcase-demo-artifact-link:architecture:preview"),
            ("lock", "showcase-input-locks:architecture"),
            ("output_closure", "showcase-closure-unlisted:README.md"),
        )
        for mutation, expected_error in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = self._fixture(Path(temporary))
                manifest_path = root / "showcase" / "showcase-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if mutation == "slug":
                    manifest["demos"][0]["slug"] = "steel"
                elif mutation == "role_link":
                    manifest["demos"][0]["artifacts"][0]["path"] = "steel/preview.png"
                elif mutation == "lock":
                    manifest["demos"][0]["inputSafetyLocks"]["accepted"] = True
                else:
                    manifest["outputClosure"]["files"] = [
                        row for row in manifest["outputClosure"]["files"]
                        if row["path"] != "README.md"
                    ]
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                errors: list[str] = []
                VERIFY.verify_showcase(root, errors)
                self.assertTrue(
                    any(error.startswith(expected_error) for error in errors),
                    errors,
                )

    def _learning_fixture(self, root: Path) -> Path:
        plugin = root / "plugins" / "aicad-agent"
        core = plugin / "runtime" / "src" / "aicad" / "continuous_learning.py"
        qa = plugin / "scripts" / "aicad_continuous_learning_qa.py"
        harvester = plugin / "scripts" / "aicad_lesson_harvester.py"
        for path in (core, qa, harvester):
            path.parent.mkdir(parents=True, exist_ok=True)
        rules = {
            "schema": VERIFY.EXPECTED_LEARNING_SCHEMA,
            "scope": VERIFY.EXPECTED_LEARNING_SCOPE,
            "canonicalEventPolicy": VERIFY.EXPECTED_LEARNING_EVENT_POLICY,
            "controls": [
                {
                    "id": f"CL-G{index:03d}",
                    "name": f"control_{index}",
                    "requirement": f"control requirement {index}",
                    "requiredRegression": f"control regression {index}",
                }
                for index in range(1, 10)
            ],
            "preventionRules": [{
                "id": "REL-G999",
                "domain": "release",
                "name": "fixture_rule",
                "symptom": "fixture symptom",
                "rootCause": "fixture root cause",
                "prevention": "fixture prevention",
                "requiredRegression": "fixture negative regression",
            }],
            "failureAliases": [{
                "alias": "release.example",
                "domain": "release",
                "ruleId": "REL-G999",
                "failingCheck": "fixture independent catalog audit",
            }],
            "candidateSafetyLocks": dict(VERIFY.EXPECTED_LEARNING_LOCKS),
            "promotionPolicy": dict(VERIFY.EXPECTED_LEARNING_POLICY),
        }
        rules_path = plugin / "rules" / "continuous_learning_rules.json"
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        rules_path.write_text(json.dumps(rules) + "\n", encoding="utf-8")
        source_plugin = ROOT / "agent-plugin" / "aicad-agent"
        source_runtime = ROOT / "src" / "aicad"
        core.write_bytes((source_runtime / "continuous_learning.py").read_bytes())
        (core.parent / "reporting.py").write_bytes((source_runtime / "reporting.py").read_bytes())
        qa.write_bytes((source_plugin / "scripts" / "aicad_continuous_learning_qa.py").read_bytes())
        harvester.write_bytes((source_plugin / "scripts" / "aicad_lesson_harvester.py").read_bytes())
        source_rules = ROOT / "agent-plugin" / "aicad-agent" / "rules"
        for name in VERIFY.LEARNING_SCHEMA_SPECS:
            target = plugin / "rules" / name
            target.write_bytes((source_rules / name).read_bytes())
        return root

    def test_github_source_learning_boundary_is_candidate_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._learning_fixture(Path(temporary))
            errors: list[str] = []
            VERIFY.verify_continuous_learning_boundary(root, errors)
            self.assertEqual([], errors)
            release_errors: list[str] = []
            rules = json.loads(
                (root / "plugins" / "aicad-agent" / "rules" / "continuous_learning_rules.json").read_text(
                    encoding="utf-8"
                )
            )
            RELEASE_VERIFY.validate_continuous_learning_catalog(rules, release_errors)
            RELEASE_VERIFY.validate_continuous_learning_runtime_boundary(
                root / "plugins" / "aicad-agent", release_errors
            )
            self.assertEqual([], release_errors)

    def _catalog(self, root: Path) -> tuple[Path, dict]:
        path = root / "plugins" / "aicad-agent" / "rules" / "continuous_learning_rules.json"
        return path, json.loads(path.read_text(encoding="utf-8"))

    def _assert_catalog_mutation_fails(self, root: Path, expected: str) -> None:
        github_errors: list[str] = []
        VERIFY.verify_continuous_learning_boundary(root, github_errors)
        self.assertIn(expected, github_errors)
        _, rules = self._catalog(root)
        release_errors: list[str] = []
        RELEASE_VERIFY.validate_continuous_learning_catalog(rules, release_errors)
        self.assertIn(expected, release_errors)

    def test_independent_learning_catalog_semantic_mutations_fail(self) -> None:
        mutations = (
            ("wrong_schema", "continuous-learning-schema"),
            ("extra_top_level", "continuous-learning-top-level-fields"),
            ("missing_control", "continuous-learning-control-inventory"),
            ("duplicate_rule", "continuous-learning-prevention-rule-inventory"),
            ("id_collision", "continuous-learning-prevention-rule-inventory"),
            ("missing_regression", "continuous-learning-required-regression"),
            ("unstable_alias", "continuous-learning-alias-inventory"),
            ("dangling_alias", "continuous-learning-alias-rule-binding"),
            ("orphan_rule", "continuous-learning-prevention-rule-coverage"),
        )
        for mutation, expected in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = self._learning_fixture(Path(temporary))
                path, rules = self._catalog(root)
                if mutation == "wrong_schema":
                    rules["schema"] = "aicad_continuous_learning_rules_v0"
                elif mutation == "extra_top_level":
                    rules["selfApproved"] = True
                elif mutation == "missing_control":
                    rules["controls"].pop()
                elif mutation == "duplicate_rule":
                    rules["preventionRules"].append(copy.deepcopy(rules["preventionRules"][0]))
                elif mutation == "id_collision":
                    rules["preventionRules"][0]["id"] = "CL-G001"
                    rules["failureAliases"][0]["ruleId"] = "CL-G001"
                elif mutation == "missing_regression":
                    rules["preventionRules"][0]["requiredRegression"] = ""
                elif mutation == "unstable_alias":
                    rules["failureAliases"][0]["alias"] = "Release Example"
                elif mutation == "dangling_alias":
                    rules["failureAliases"][0]["ruleId"] = "REL-G998"
                else:
                    extra = copy.deepcopy(rules["preventionRules"][0])
                    extra["id"] = "REL-G998"
                    rules["preventionRules"].append(extra)
                path.write_text(json.dumps(rules) + "\n", encoding="utf-8")
                self._assert_catalog_mutation_fails(root, expected)

    def test_each_learning_lock_and_promotion_policy_mutation_fails(self) -> None:
        for section, expected in (
            ("candidateSafetyLocks", "continuous-learning-locks"),
            ("promotionPolicy", "continuous-learning-promotion-policy"),
        ):
            baseline = (
                VERIFY.EXPECTED_LEARNING_LOCKS
                if section == "candidateSafetyLocks"
                else VERIFY.EXPECTED_LEARNING_POLICY
            )
            for key in baseline:
                with self.subTest(section=section, key=key), tempfile.TemporaryDirectory() as temporary:
                    root = self._learning_fixture(Path(temporary))
                    path, rules = self._catalog(root)
                    rules[section][key] = not rules[section][key]
                    path.write_text(json.dumps(rules) + "\n", encoding="utf-8")
                    self._assert_catalog_mutation_fails(root, expected)

    def test_learning_schema_document_mutations_fail_at_both_release_boundaries(self) -> None:
        mutations = ("invalid_json", "wrong_draft", "missing_definition", "dangling_ref", "required_not_declared")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = self._learning_fixture(Path(temporary))
                plugin = root / "plugins" / "aicad-agent"
                path = plugin / "rules" / "learning_event.schema.json"
                if mutation == "invalid_json":
                    path.write_text("{", encoding="utf-8")
                else:
                    schema = json.loads(path.read_text(encoding="utf-8"))
                    if mutation == "wrong_draft":
                        schema["$schema"] = "https://json-schema.org/draft/2019-09/schema"
                    elif mutation == "missing_definition":
                        del schema["$defs"]["lesson"]
                    elif mutation == "dangling_ref":
                        schema["oneOf"][0]["$ref"] = "#/$defs/doesNotExist"
                    else:
                        schema["$defs"]["failedCheck"]["required"].append("undeclaredField")
                    path.write_text(json.dumps(schema) + "\n", encoding="utf-8")
                github_errors: list[str] = []
                VERIFY.verify_continuous_learning_boundary(root, github_errors)
                expected = "continuous-learning-schema-document:learning_event.schema.json"
                self.assertIn(expected, github_errors)
                release_errors: list[str] = []
                RELEASE_VERIFY.validate_learning_schema_documents(plugin, release_errors)
                self.assertIn(expected, release_errors)

    def test_release_version_verifier_rejects_mutually_consistent_stale_metadata(self) -> None:
        stale = {
            "version": "1.13.0",
            "componentVersions": {
                "agentPlugin": "1.13.0",
                "pythonConstraintCompiler": "1.13.0",
            },
        }
        errors: list[str] = []
        RELEASE_VERIFY.verify_release_versions(
            {"version": "1.13.0"}, stale, "1.15.1", errors
        )
        self.assertIn("expected-version-mismatch", errors)
        self.assertIn("component-version-mismatch", errors)
        self.assertNotIn("version-mismatch", errors)

    def test_release_version_verifier_rejects_component_drift(self) -> None:
        manifest = {
            "version": "1.15.1",
            "componentVersions": {
                "agentPlugin": "1.15.1",
                "pythonConstraintCompiler": "1.13.0",
            },
        }
        errors: list[str] = []
        RELEASE_VERIFY.verify_release_versions(
            {"version": "1.15.1"}, manifest, "1.15.1", errors
        )
        self.assertEqual(["component-version-mismatch"], errors)

    def test_github_source_learning_harvester_output_boundary_mutation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._learning_fixture(Path(temporary))
            plugin = root / "plugins" / "aicad-agent"
            path = plugin / "scripts" / "aicad_lesson_harvester.py"
            text = path.read_text(encoding="utf-8")
            text = text.replace("_atomic_json(root, output, bundle)", "_atomic_json(root, args.output, bundle)")
            path.write_text(text, encoding="utf-8")
            errors: list[str] = []
            VERIFY.verify_continuous_learning_boundary(root, errors)
            self.assertIn("continuous-learning-harvester-output-boundary", errors)
            release_errors: list[str] = []
            RELEASE_VERIFY.validate_continuous_learning_runtime_boundary(plugin, release_errors)
            self.assertIn("continuous-learning-harvester-output-boundary", release_errors)

    def test_learning_authorization_assignments_are_checked_by_ast_not_strings(self) -> None:
        for surface, relative, field in (
            ("core", "runtime/src/aicad/continuous_learning.py", "technicalPackageReady"),
            ("qa", "scripts/aicad_continuous_learning_qa.py", "manufacturingAuthorized"),
            ("harvester", "scripts/aicad_lesson_harvester.py", "fabricationAuthorized"),
        ):
            with self.subTest(surface=surface), tempfile.TemporaryDirectory() as temporary:
                root = self._learning_fixture(Path(temporary))
                path = root / "plugins" / "aicad-agent" / relative
                text = path.read_text(encoding="utf-8")
                old = f'"{field}": False'
                self.assertIn(old, text)
                path.write_text(text.replace(old, f'"{field}": True', 1) + f'\n# {old}\n', encoding="utf-8")
                errors: list[str] = []
                VERIFY.verify_continuous_learning_boundary(root, errors)
                prefix = f"continuous-learning-{surface}-authorization:{field}:"
                self.assertTrue(any(error.startswith(prefix) for error in errors), errors)
                release_errors: list[str] = []
                RELEASE_VERIFY.validate_continuous_learning_runtime_boundary(
                    root / "plugins" / "aicad-agent", release_errors
                )
                self.assertTrue(any(error.startswith(prefix) for error in release_errors), release_errors)

    def test_runtime_boundary_rejects_exact_key_schema_and_authoritative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._learning_fixture(Path(temporary))
            errors: list[str] = []
            VERIFY.verify_continuous_learning_boundary(root, errors)
            self.assertEqual([], errors)
            plugin = root / "plugins" / "aicad-agent"
            module, names = VERIFY._load_learning_runtime(plugin)
            try:
                for unsafe in (
                    "rules/continuous_learning_rules.json", "scripts/aicad_lesson_harvester.py",
                    "runtime/src/aicad/continuous_learning.py", ".codex-plugin/plugin.json",
                ):
                    with self.subTest(unsafe=unsafe), self.assertRaises(module.ReportInvariantError):
                        module.controlled_learning_output_path(unsafe)
            finally:
                for name in reversed(names):
                    VERIFY.sys.modules.pop(name, None)

    def test_release_metadata_loader_rejects_non_objects_without_throwing(self) -> None:
        for label, payload in (("plugin-metadata", []), ("integration-manifest", "bad")):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "metadata.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                errors: list[str] = []
                self.assertEqual({}, RELEASE_VERIFY.load_metadata_object(path, label, errors))
                self.assertEqual([f"{label}-not-object"], errors)

    def test_release_verify_returns_structured_errors_for_non_object_metadata(self) -> None:
        for filename, payload, expected in (
            (".codex-plugin/plugin.json", [], "plugin-metadata-not-object"),
            ("integration-manifest.json", "bad", "integration-manifest-not-object"),
        ):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                plugin_path = root / ".codex-plugin" / "plugin.json"
                plugin_path.parent.mkdir(parents=True)
                plugin_path.write_text(json.dumps({"name": "aicad-agent", "version": "1.15.1"}), encoding="utf-8")
                manifest_path = root / "integration-manifest.json"
                manifest_path.write_text(json.dumps({"version": "1.15.1", "files": []}), encoding="utf-8")
                (root / "SHA256SUMS").write_text("", encoding="utf-8")
                target = root / filename
                target.write_text(json.dumps(payload), encoding="utf-8")
                result = RELEASE_VERIFY.verify(root)
                self.assertFalse(result["ok"])
                self.assertIn(expected, result["errors"])


if __name__ == "__main__":
    unittest.main()
