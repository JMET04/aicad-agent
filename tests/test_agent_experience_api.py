from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "agent-plugin" / "aicad-agent"
SCRIPT = PLUGIN / "scripts" / "aicad_agent.py"
RULES = PLUGIN / "rules"

sys.path.insert(0, str(ROOT / "src"))

from aicad.experience import EXPECTED_LOCKS, populate_coverage_for_test


def load_agent():
    spec = importlib.util.spec_from_file_location("aicad_agent_experience_api", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load AICAD agent plugin")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def civil_context() -> dict:
    return {
        "schema": "aicad_design_context_v1",
        "contextId": "CTX_CIVIL_API",
        "domain": "civil",
        "spaces": ["2d", "3d"],
        "deliveryStage": "engineering_review",
        "productFamilies": [],
        "riskTags": ["interface"],
        "changeTags": ["geometry"],
        "requestedOutputs": ["review_html"],
        "applicableStandards": [
            {
                "standard": "PROJECT-SPEC",
                "edition": "CONTROLLED",
                "scope": "civil",
                "authority": "approved_engineering_input",
            }
        ],
        "assumptions": [],
        "locks": dict(EXPECTED_LOCKS),
    }


class AgentExperienceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.agent = load_agent()

    def test_capabilities_and_tool_contract_expose_complete_experience_surface(self) -> None:
        capability = self.agent.capabilities()["experience_recall_and_coverage"]
        self.assertTrue(capability["available"])
        self.assertEqual(capability["workflow_position"], "after domain resolution and before geometry")
        self.assertEqual(len(capability["registered_domains"]), 13)
        self.assertTrue(capability["exact_coverage_inventory_required"])
        self.assertTrue(capability["rule_source_hash_closure_required"])
        self.assertTrue(capability["evidence_file_hash_revalidation_required"])
        self.assertFalse(capability["candidate_lessons_may_satisfy_coverage"])
        self.assertFalse(capability["professional_release_granted"])
        for field in ("domain_registry", "catalog", "context_schema", "coverage_schema"):
            self.assertTrue(Path(capability[field]).is_file(), field)

        tools = {row["name"]: row for row in self.agent.TOOLS}
        expected = {
            "aicad_get_experience_context_schema",
            "aicad_get_review_coverage_schema",
            "aicad_get_engineering_domain_registry",
            "aicad_recall_experience",
            "aicad_validate_review_coverage",
        }
        self.assertTrue(expected.issubset(tools))
        for name in expected:
            schema = tools[name]["inputSchema"]
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])
        self.assertEqual(tools["aicad_recall_experience"]["inputSchema"]["required"], ["context"])
        self.assertEqual(
            tools["aicad_validate_review_coverage"]["inputSchema"]["required"],
            ["recall", "ledger", "evidence_root"],
        )

    def test_schema_and_registry_tools_match_declared_mcp_resources(self) -> None:
        cases = (
            (
                "aicad_get_experience_context_schema",
                "aicad://experience-context-schema",
                "schema",
                "application/schema+json",
            ),
            (
                "aicad_get_review_coverage_schema",
                "aicad://review-coverage-schema",
                "schema",
                "application/schema+json",
            ),
            (
                "aicad_get_engineering_domain_registry",
                "aicad://engineering-domain-registry",
                "registry",
                "application/json",
            ),
        )
        listing = self.agent._handle_mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {}}
        )
        listed = {row["uri"]: row for row in listing["result"]["resources"]}
        for tool_name, uri, field, mime_type in cases:
            with self.subTest(uri=uri):
                tool_payload = self.agent._dispatch_tool(tool_name, {})
                self.assertTrue(tool_payload["ok"])
                if field == "schema":
                    Draft202012Validator.check_schema(tool_payload[field])
                else:
                    self.assertEqual(tool_payload[field]["schema"], "aicad_engineering_domain_registry_v1")
                    self.assertEqual(len(tool_payload[field]["domains"]), 13)
                    self.assertEqual(tool_payload[field]["safetyLocks"], EXPECTED_LOCKS)
                self.assertEqual(listed[uri]["mimeType"], mime_type)
                resource = self.agent._handle_mcp(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "resources/read",
                        "params": {"uri": uri},
                    }
                )
                content = resource["result"]["contents"][0]
                self.assertEqual(content["mimeType"], mime_type)
                self.assertEqual(json.loads(content["text"]), tool_payload[field])

    def test_recall_and_real_evidence_validation_work_through_mcp_dispatch(self) -> None:
        recall_call = self.agent._handle_mcp(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "aicad_recall_experience",
                    "arguments": {"context": civil_context(), "max_cards": 2},
                },
            }
        )
        self.assertNotIn("isError", recall_call["result"])
        recalled = recall_call["result"]["structuredContent"]
        self.assertTrue(recalled["ok"])
        self.assertEqual(recalled["domainProfile"]["id"], "civil")
        civil_rules = {
            row["coverageKey"]
            for row in recalled["coverageInventory"]
            if row["coverageKey"].startswith("rule:civil:CIV-G")
        }
        self.assertEqual(civil_rules, {f"rule:civil:CIV-G{index:03d}" for index in range(1, 21)})

        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            ledger = populate_coverage_for_test(recalled, evidence_root=evidence_root)
            validation_call = self.agent._handle_mcp(
                {
                    "jsonrpc": "2.0",
                    "id": 11,
                    "method": "tools/call",
                    "params": {
                        "name": "aicad_validate_review_coverage",
                        "arguments": {
                            "recall": recalled,
                            "ledger": ledger,
                            "evidence_root": str(evidence_root),
                        },
                    },
                }
            )
            validated = validation_call["result"]["structuredContent"]
            self.assertTrue(validated["ok"])
            self.assertTrue(
                all(value is False for value in validated["readinessBoundary"].values())
            )

            missing_root = self.agent._handle_mcp(
                {
                    "jsonrpc": "2.0",
                    "id": 12,
                    "method": "tools/call",
                    "params": {
                        "name": "aicad_validate_review_coverage",
                        "arguments": {"recall": recalled, "ledger": ledger},
                    },
                }
            )["result"]
            self.assertTrue(missing_root["isError"])
            self.assertEqual(missing_root["structuredContent"]["error"]["code"], "PLAN_INVALID")

    def test_context_file_path_uses_same_recall_dispatch_as_object(self) -> None:
        direct = self.agent._dispatch_tool(
            "aicad_recall_experience", {"context": civil_context()}
        )
        with tempfile.TemporaryDirectory() as directory:
            context_path = Path(directory) / "context.json"
            context_path.write_text(
                json.dumps(civil_context(), ensure_ascii=False), encoding="utf-8"
            )
            from_path = self.agent._dispatch_tool(
                "aicad_recall_experience", {"context": str(context_path)}
            )
        self.assertEqual(from_path["contextFingerprint"], direct["contextFingerprint"])
        self.assertEqual(from_path["catalogFingerprint"], direct["catalogFingerprint"])
        self.assertEqual(from_path["coverageInventory"], direct["coverageInventory"])

    def test_stdio_mcp_process_lists_and_calls_new_surface(self) -> None:
        messages = [
            {
                "jsonrpc": "2.0",
                "id": 20,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26"},
            },
            {"jsonrpc": "2.0", "id": 21, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 22, "method": "resources/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 23,
                "method": "tools/call",
                "params": {
                    "name": "aicad_get_engineering_domain_registry",
                    "arguments": {},
                },
            },
        ]
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "mcp"],
            cwd=ROOT,
            input="".join(json.dumps(message) + "\n" for message in messages),
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        responses = {
            row["id"]: row
            for row in (
                json.loads(line) for line in completed.stdout.splitlines() if line.strip()
            )
        }
        self.assertEqual(set(responses), {20, 21, 22, 23})
        self.assertEqual(responses[20]["result"]["serverInfo"]["name"], "aicad-agent")
        tool_names = {row["name"] for row in responses[21]["result"]["tools"]}
        self.assertIn("aicad_recall_experience", tool_names)
        resource_uris = {row["uri"] for row in responses[22]["result"]["resources"]}
        self.assertIn("aicad://engineering-domain-registry", resource_uris)
        registry = responses[23]["result"]["structuredContent"]["registry"]
        self.assertEqual(len(registry["domains"]), 13)


if __name__ == "__main__":
    unittest.main()
