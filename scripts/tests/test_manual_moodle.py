"""Safety/orchestration checks with a fake Docker runner; no daemon is used."""

from __future__ import annotations

import argparse
import copy
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "manual-moodle.py"
spec = importlib.util.spec_from_file_location("manual_moodle", SCRIPT)
manual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manual)


def container(service="backend", marker=None):
    labels = {"com.docker.compose.project": "lab", "com.docker.compose.service": service}
    if marker:
        labels[manual.MARKER] = marker
    port = "18081" if service == "frontend" else "18080"
    return {"Id": service + "-original", "Image": "sha256:" + service,
        "Config": {"Labels": labels, "Env": ["CORS_ORIGINS=http://localhost:18082,https://other.example",
            "COLLECTOR_INGEST_KEY=ingestion-key-for-tests", "COLLECTOR_AUTH_SECRET=secret-for-tests",
            "MONGODB_ROOT_PASSWORD=original$money"]},
        "State": {"Running": True},
        "HostConfig": {"NanoCpus": 2_000_000_000, "Memory": 2 * 1024**3,
                       "PortBindings": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]}},
        "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]},
                            "Networks": {"lab_collector": {}}}}


def configuration():
    return {"name": "lab", "services": {"backend": {
        "build": {"context": "/repository/server"}, "depends_on": {"mongodb": {"condition": "service_healthy"}},
        "environment": {"CORS_ORIGINS": "stale-on-disk", "MONGODB_ROOT_PASSWORD": "stale-on-disk"},
        "ports": [{"target": 8080, "published": "18080", "host_ip": "127.0.0.1", "protocol": "tcp"}],
        "networks": {"collector": None}, "cpus": 2.0, "mem_limit": 2 * 1024**3,
        "healthcheck": {"test": ["CMD", "python", "-c", "print('health')"]},
        "restart": "unless-stopped"}}, "networks": {"collector": {"name": "lab_collector"}}}


class Docker(manual.Runner):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.backend = container()
        self.fail_restore = False
        self.fail_reload = False
        self.fail_install = False

    def service(self, project, service):
        return copy.deepcopy(self.backend if service == "backend" else container(service))

    def run(self, args, *, timeout=60):
        args = list(args)
        self.calls.append(args)
        if args[-3:] == ["config", "--format", "json"]:
            return json.dumps(configuration())
        if args[:3] == ["docker", "image", "inspect"]:
            return json.dumps([{"Id": "sha256:" + args[-1]}])
        if args[0] != "docker":
            # The separate packaging check invokes the real packager. Here only
            # the orchestration contract and destination are relevant.
            Path(args[-1]).write_bytes(b"archive-placeholder")
            return ""
        if "-f" in args:
            path = Path(args[args.index("-f") + 1])
            if "up" in args:
                if path.name == "moodle.json" and self.fail_install:
                    raise manual.RehearsalError("Moodle install failed")
                if path.name.startswith("collector-"):
                    if path.name == "collector-original.json" and self.fail_restore:
                        raise manual.RehearsalError("restore failed")
                    doc = json.loads(path.read_text())["services"]["backend"]
                    self.backend["Id"] += "-recreated"
                    self.backend["Config"]["Labels"] = doc["labels"]
                    self.backend["Config"]["Env"] = [f"{key}={value.replace('$$', '$')}" for key, value in doc["environment"].items()]
        if "nginx" in args and self.fail_reload:
            raise manual.RehearsalError("nginx reload failed")
        return ""


class ManualRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temporary.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.env = self.repo / ".env"
        self.env.write_text("KEEP=original\n")
        self.folder = self.tmp / "control"
        self.folder.mkdir(mode=0o700)
        self.runner = Docker()
        self.token = "a" * 32
        self.args = argparse.Namespace(compose_file=[], port=0, moodle_image=None, mariadb_image=None)
        self.patches = [patch.object(manual, "TMP", self.tmp), patch.object(manual, "ROOT", self.repo),
                        patch.object(manual, "free_port", return_value=44620), patch.object(manual, "probe")]
        for item in self.patches:
            item.start()
        self.output = io.StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()

    def tearDown(self):
        self.redirect.__exit__(None, None, None)
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def start(self):
        return manual.start(self.runner, self.folder, self.args, self.token)

    def test_start_uses_separate_tmpfs_site_and_restores_original_collector(self):
        original_env = manual.environment(self.runner.backend)
        state = self.start()
        work = Path(state["work"])
        doc = json.loads((work / "moodle.json").read_text())
        self.assertEqual(set(doc["services"]), {"moodle", "mariadb"})
        self.assertNotIn("volumes", doc)
        for service in doc["services"].values():
            self.assertEqual(service["restart"], "no")
            self.assertEqual(service["pull_policy"], "never")
            self.assertNotIn("build", service)
            self.assertTrue(service["tmpfs"])
        self.assertNotIn("COLLECTOR_INGEST_KEY", doc["services"]["moodle"]["environment"])
        self.assertTrue(all(mount["read_only"] for mount in doc["services"]["moodle"]["volumes"]))
        self.assertEqual(manual.environment(self.runner.backend)["CORS_ORIGINS"],
            original_env["CORS_ORIGINS"] + ",http://localhost:44620")
        manual.cleanup(self.runner, self.folder)
        self.assertEqual(manual.environment(self.runner.backend), original_env)
        self.assertFalse(work.exists())
        self.assertIsNone(manual.read_state(self.folder))
        self.assertEqual(self.env.read_text(), "KEEP=original\n")
        for call in self.runner.calls:
            self.assertNotIn("build", call)
            self.assertNotIn("pull", call)
            if "down" in call:
                self.assertEqual(Path(call[call.index("-f") + 1]).name, "moodle.json")
                self.assertEqual(call[call.index("-p") + 1], state["project"])

    def test_backend_snapshot_pins_runtime_image_environment_limits_and_external_network(self):
        doc = manual.backend_document(configuration(), self.runner.backend)
        backend = doc["services"]["backend"]
        self.assertEqual(backend["image"], self.runner.backend["Image"])
        self.assertEqual(backend["environment"]["MONGODB_ROOT_PASSWORD"], "original$money")
        self.assertEqual(backend["cpus"], 2.0)
        self.assertEqual(backend["mem_limit"], 2 * 1024**3)
        self.assertEqual(doc["networks"], {"collector": {"external": True, "name": "lab_collector"}})
        self.assertNotIn("build", backend)
        self.assertNotIn("depends_on", backend)

    def test_compose_snapshots_preserve_literal_dollars_and_have_private_permissions(self):
        path = self.tmp / "literal.json"
        manual.write_json(path, {"password": "x$HOME${NOPE}$$tail"}, compose=True)
        self.assertEqual(json.loads(path.read_text())["password"], "x$$HOME$${NOPE}$$$$tail")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failed_restore_keeps_recovery_state_and_can_retry(self):
        state = self.start()
        self.runner.fail_restore = True
        with self.assertRaises(manual.RehearsalError):
            manual.cleanup(self.runner, self.folder)
        self.assertTrue(Path(state["work"]).exists())
        self.assertIsNotNone(manual.read_state(self.folder))
        self.runner.fail_restore = False
        manual.cleanup(self.runner, self.folder)
        self.assertIsNone(manual.read_state(self.folder))

    def test_nginx_reload_failure_retries_without_replacing_backend_again(self):
        self.start()
        self.runner.fail_reload = True
        with self.assertRaises(manual.RehearsalError):
            manual.cleanup(self.runner, self.folder)
        restored_id = self.runner.backend["Id"]
        self.runner.fail_reload = False
        manual.cleanup(self.runner, self.folder)
        self.assertEqual(self.runner.backend["Id"], restored_id)

    def test_external_backend_change_is_not_reverted(self):
        self.start()
        self.runner.backend["Id"] = "external-deployment"
        self.runner.backend["Config"]["Labels"].pop(manual.MARKER)
        before = copy.deepcopy(self.runner.backend)
        manual.cleanup(self.runner, self.folder)
        self.assertEqual(self.runner.backend, before)

    def test_install_failure_does_not_recreate_collector(self):
        self.runner.fail_install = True
        with self.assertRaises(manual.RehearsalError):
            self.start()
        manual.cleanup(self.runner, self.folder, token=self.token)
        self.assertEqual(self.runner.backend["Id"], "backend-original")
        self.assertFalse(any("collector-cors.json" in " ".join(call) for call in self.runner.calls))

    def test_second_start_and_wrong_cleanup_token_leave_running_site_intact(self):
        state = self.start()
        with self.assertRaises(manual.RehearsalError):
            self.start()
        manual.cleanup(self.runner, self.folder, token="b" * 32)
        self.assertTrue(Path(state["work"]).exists())

    def test_mismatching_runtime_ports_fail_before_reconfiguration(self):
        config = configuration()
        config["services"]["backend"]["ports"][0]["published"] = "19999"
        with self.assertRaises(manual.RehearsalError):
            manual.backend_document(config, self.runner.backend)

    def test_cleanup_refuses_paths_outside_its_own_temporary_project(self):
        manual.write_json(self.folder / "state.json", {"token": self.token,
            "work": str(self.repo), "project": "lab"})
        with self.assertRaises(manual.RehearsalError):
            manual.cleanup(self.runner, self.folder)
        self.assertTrue(self.env.exists())
        self.assertEqual(self.runner.calls, [])

    def test_error_redaction_does_not_print_saved_passwords(self):
        self.start()
        self.assertNotIn("original$money", self.runner.redact("failed original$money"))

    def test_foreground_command_cleans_up_on_enter(self):
        which = lambda name: "/bin/docker" if name == "docker" else None
        with patch.object(manual, "Runner", return_value=self.runner), \
                patch.object(manual, "control_directory", return_value=self.folder), \
                patch.object(manual.shutil, "which", side_effect=which), \
                patch("builtins.input", return_value=""):
            self.assertEqual(manual.main(["start"]), 0)
        self.assertIsNone(manual.read_state(self.folder))

    def test_foreground_command_reports_cleanup_failure_with_nonzero_exit(self):
        self.runner.fail_restore = True
        which = lambda name: "/bin/docker" if name == "docker" else None
        errors = io.StringIO()
        with patch.object(manual, "Runner", return_value=self.runner), \
                patch.object(manual, "control_directory", return_value=self.folder), \
                patch.object(manual.shutil, "which", side_effect=which), \
                patch("builtins.input", side_effect=KeyboardInterrupt), redirect_stderr(errors):
            self.assertEqual(manual.main(["start"]), 1)
        self.assertIsNotNone(manual.read_state(self.folder))
        self.assertIn("Очистка не завершена", errors.getvalue())


class CorsProbeTests(unittest.TestCase):
    def test_inherited_remove_orphans_cannot_delete_main_services(self):
        runner = manual.Runner()
        result = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch.dict(os.environ, {"COMPOSE_REMOVE_ORPHANS": "true"}), \
                patch.object(manual.subprocess, "run", return_value=result) as run:
            self.assertEqual(runner.run(["docker", "compose", "version"]), "ok")
            self.assertEqual(run.call_args.kwargs["env"]["COMPOSE_REMOVE_ORPHANS"], "false")
            self.assertEqual(os.environ["COMPOSE_REMOVE_ORPHANS"], "true")

    def test_success_and_wrong_origin(self):
        state = {"collector_url": "http://localhost:18081", "moodle_url": "http://localhost:44620"}
        response = MagicMock(status=200, headers={"Access-Control-Allow-Origin": state["moodle_url"]})
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(manual, "build_opener", return_value=opener):
            manual.probe(state)
            response.headers = {"Access-Control-Allow-Origin": "http://localhost:18082"}
            with self.assertRaises(manual.RehearsalError):
                manual.probe(state)


if __name__ == "__main__":
    unittest.main()
