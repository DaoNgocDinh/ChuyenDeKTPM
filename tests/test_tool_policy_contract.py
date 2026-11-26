import json
import unittest
from dataclasses import replace
from pathlib import Path

from backend.runner_profile import RunnerProfile


POLICY = json.loads((Path(__file__).parents[1] / "docs/quyen-cong-cu.json").read_text(encoding="utf-8"))
ROLES = POLICY["roles"]


class PolicyDesignTests(unittest.TestCase):
    def test_read_and_write_zones_match_all_six_roles(self):
        zones = {"Orchestrator": [], "Requirement": [], "Architecture": [],
                 "Planning": [], "Dev": ["app"], "Tester": ["tests_dev"]}
        self.assertEqual({name: role["write"] for name, role in ROLES.items()}, zones)
        for role in ROLES.values():
            self.assertIn("project.read_artifact", role["read"])
            self.assertNotIn("evaluation", role.get("read_roots", []) + role["write"])

    def test_only_dev_and_tester_can_call_named_suites(self):
        self.assertEqual({name for name, role in ROLES.items() if role["suites"]}, {"Dev", "Tester"})
        for name in ("Dev", "Tester"):
            self.assertEqual(set(ROLES[name]["suites"]), {"build", "smoke", "development"})
        self.assertEqual(POLICY["runner"]["independent_suite_access"], "evaluation_host_only")

    def test_host_context_binds_step_and_input(self):
        self.assertEqual(set(POLICY["trusted_context"]),
                         {"project_id", "run_id", "step_id", "role", "task_id", "input_commit"})

    def test_runner_requires_all_limits_and_no_host_privileges(self):
        runner = POLICY["runner"]
        self.assertEqual(runner["backend"], "docker")
        self.assertTrue(runner["read_only_root"])
        self.assertFalse(any(runner[k] for k in ("privileged", "host_socket", "run_as_root")))
        self.assertTrue({"image_digest", "argv", "cwd", "executable", "network_policy", "timeout_seconds",
                         "cpu_limit", "memory_bytes", "pids_limit", "output_limit_bytes"} <= set(runner["profile_fields"]))
        self.assertFalse(runner["environment_allowlist"])
        self.assertEqual(runner["resource_limits"],
                         dict(cpu_limit=2, memory_bytes=2 * 1024**3, pids_limit=128,
                              timeout_seconds=180, output_limit_bytes=1024**2))

    def test_profile_requires_pinned_image_limits_and_bridge(self):
        # Values are test data only. No production defaults are set.
        p = RunnerProfile("development", "test/image@sha256:" + "a" * 64,
                          "/usr/bin/python", ("-m", "pytest"), "/workspace",
                          POLICY["runner"]["network"]["test_egress"], 1, 0.5, 1024, 2, 128)
        self.assertEqual(set(p.__dataclass_fields__), set(POLICY["runner"]["profile_fields"]))
        self.assertIn("--read-only", p.docker_options())
        self.assertEqual(p.docker_options()[:2], ("--network", "bridge"))
        for change in ({"image_digest": "test/image:latest"}, {"timeout_seconds": 0},
                       {"network_policy": "host"}, {"cwd": "/workspace/../host"},
                       {"cpu_limit": float("nan")}, {"output_limit_bytes": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(p, **change)
