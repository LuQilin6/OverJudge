"""Regression tests for immutable revisions, provenance, and release invalidation."""

import json
from pathlib import Path
import tempfile
import unittest

from src.artifacts import ArtifactStore, compute_cache_key
from src.contracts import ContractError


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ArtifactStore(self.root, "fight_1")

    def prepare(self, stage="B", context=None, prompt="Observe supplied evidence."):
        return self.store.save_request(stage, context or {"inputs": {"video": "a" * 64}}, prompt)

    def save(self, stage="B", summary="first", status="PASS"):
        self.prepare(stage)
        return self.store.save_result(stage, {"summary": summary}, f"# {summary}\n", {"status": status})

    def index(self):
        return json.loads(self.store.metadata_path.read_text())

    def test_request_preserves_context_and_uses_exact_hashes(self):
        context = {"evidence_refs": ["tank@1.0-2.0"], "api_key_env": "PROVIDER_API_KEY"}
        path = self.prepare(context=context)
        metadata = json.loads((path / "request_metadata.json").read_text())
        self.assertEqual(json.loads((path / "context.json").read_text()), context)
        self.assertEqual(metadata["cache_key"], compute_cache_key("B", context, "Observe supplied evidence."))
        self.assertTrue((path / "prompt.md").is_file())
        self.assertNotEqual(path, self.prepare(context=context))

    def test_cache_tracks_stage_inputs_prompt_and_tools(self):
        base = compute_cache_key("B", {"source_hash": "first"}, "v1")
        self.assertEqual(base, compute_cache_key("B", {"source_hash": "first"}, "v1"))
        alternatives = [compute_cache_key("C", {"source_hash": "first"}, "v1"),
                        compute_cache_key("B", {"source_hash": "second"}, "v1"),
                        compute_cache_key("B", {"source_hash": "first"}, "v2"),
                        compute_cache_key("B", {"source_hash": "first"}, "v1", {"model": "other"})]
        self.assertTrue(all(value != base for value in alternatives))

    def test_result_revisions_are_immutable_and_index_tracks_latest(self):
        first = self.save()
        second = self.save(summary="second")
        self.assertNotEqual(first["result_path"], second["result_path"])
        self.assertEqual(json.loads(Path(first["result_path"]).read_text())["summary"], "first")
        self.assertEqual(self.store.load_result("B")["summary"], "second")
        self.assertEqual(len(self.index()["stages"]["B"]["history"]), 2)
        self.assertEqual(Path(second["report_path"]).name, "fusion.md")
        self.assertEqual(Path(self.save("C")["report_path"]).name, "verdict.md")
        self.assertEqual(Path(self.save("D")["report_path"]).name, "qa_report.md")

    def test_later_error_hides_previous_pass(self):
        self.save()
        self.store.record_status("B", "BLOCKED", {"error": "Missing source"})
        self.assertIsNone(self.store.latest("B"))
        self.assertEqual(len(self.index()["stages"]["B"]["history"]), 1)

    def test_invalidate_c_keeps_b_and_archived_results_but_revokes_release(self):
        records = {stage: self.save(stage) for stage in ("B", "C", "D")}
        release = self.store.write_release("QA passed", "Final verdict", {"status": "PASS"})
        self.store.invalidate_from("C")
        self.assertIsNotNone(self.store.latest("B"))
        self.assertIsNone(self.store.latest("C"))
        self.assertIsNone(self.store.latest("D"))
        self.assertIsNone(self.index()["release"]["latest"])
        self.assertTrue(Path(release["final_path"]).is_file())
        self.assertTrue(all(Path(record["result_path"]).is_file() for record in records.values()))

    def test_fail_release_does_not_expose_old_passing_final(self):
        old = self.store.write_release("QA passed", "Final verdict", {"status": "PASS"})
        new = self.store.write_release("Critical error", None, {"status": "FAIL"})
        self.assertFalse(new["published"])
        self.assertIsNone(new["final_path"])
        self.assertIsNone(self.index()["release"]["latest"]["final_path"])
        self.assertTrue(Path(old["final_path"]).is_file())
        with self.assertRaises(ContractError):
            self.store.write_release("Critical error", "Unsupported final", {"status": "FAIL"})

    def test_tampered_or_missing_artifact_is_rejected(self):
        record = self.save()
        Path(record["result_path"]).write_text('{"summary":"changed"}')
        with self.assertRaisesRegex(ContractError, "hash mismatch"):
            self.store.load_result("B")
        record = self.save()
        Path(record["report_path"]).unlink()
        with self.assertRaisesRegex(ContractError, "missing"):
            self.store.latest("B")

    def test_index_path_cannot_escape_run(self):
        self.save()
        data = self.index()
        data["stages"]["B"]["latest"]["result_path"] = str(self.root / "outside.json")
        self.store.metadata_path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ContractError, "escapes"):
            self.store.latest("B")

    def test_run_and_stage_ids_cannot_escape_output(self):
        for run_id in ("../escape", "/absolute", "..", "bad/name", "", ".hidden"):
            with self.subTest(run_id=run_id), self.assertRaises(ContractError):
                ArtifactStore(self.root, run_id)
        with self.assertRaises(ContractError):
            self.store.stage_dir("../B")

    def test_existing_symlink_cannot_redirect_output(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.store.run_dir / "stages").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ContractError, "escapes"):
                self.store.stage_dir("B")

    def test_symlink_inside_output_cannot_redirect_to_another_run(self):
        another = ArtifactStore(self.root, "fight_2")
        (self.store.run_dir / "stages").symlink_to(another.run_dir, target_is_directory=True)
        with self.assertRaisesRegex(ContractError, "symlinks"):
            self.store.stage_dir("B")

    def test_missing_required_index_paths_are_not_silently_accepted(self):
        self.save()
        data = self.index()
        del data["stages"]["B"]["latest"]["report_path"]
        self.store.metadata_path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ContractError, "invalid path or hash"):
            self.store.latest("B")

    def test_release_compare_and_swap_accepts_current_revisions(self):
        expected = {stage: self.save(stage)["revision_id"] for stage in ("B", "C", "D")}
        release = self.store.write_release("QA passed", "Final verdict", {
            "status": "PASS", "expected_stage_revisions": expected})
        self.assertTrue(release["published"])

    def test_release_compare_and_swap_rejects_changed_upstream(self):
        expected = {stage: self.save(stage)["revision_id"] for stage in ("B", "C", "D")}
        self.store.invalidate_from("C")
        with self.assertRaisesRegex(ContractError, "inputs changed"):
            self.store.write_release("QA passed", "Stale final", {
                "status": "PASS", "expected_stage_revisions": expected})
        self.assertIsNone(self.index()["release"]["latest"])

    def test_release_compare_and_swap_preserves_latest_on_concurrent_failure(self):
        expected = {stage: self.save(stage)["revision_id"] for stage in ("B", "C", "D")}
        passed = self.store.write_release("QA passed", "Final verdict", {
            "status": "PASS", "expected_stage_revisions": expected})
        self.store.record_status("C", "FAIL", {"error": "Changed input"})
        with self.assertRaisesRegex(ContractError, "inputs changed"):
            self.store.write_release("QA passed", "Stale final", {
                "status": "PASS", "expected_stage_revisions": expected})
        self.assertEqual(self.index()["release"]["latest"]["revision_id"], passed["revision_id"])

    def test_failed_qa_can_be_archived_under_revision_compare_and_swap(self):
        expected = {stage: self.save(stage, status="FAIL" if stage == "D" else "PASS")["revision_id"]
                    for stage in ("B", "C", "D")}
        release = self.store.write_release("QA failed", None, {
            "status": "FAIL", "expected_stage_revisions": expected})
        self.assertFalse(release["published"])
        self.assertEqual(self.index()["release"]["latest"]["status"], "FAIL")

    def test_result_compare_and_swap_accepts_current_inputs_and_request(self):
        source = self.save("B")
        request = self.prepare("C")
        request_revision = json.loads((request / "request_metadata.json").read_text())["revision_id"]
        record = self.store.save_result("C", {"summary": "current"}, "Current verdict", {
            "status": "PASS", "expected_stage_revisions": {"B": source["revision_id"]},
            "expected_request_revision": request_revision})
        self.assertEqual(self.store.latest("C")["revision_id"], record["revision_id"])

    def test_result_compare_and_swap_rejects_superseded_request(self):
        request = self.prepare("B")
        request_revision = json.loads((request / "request_metadata.json").read_text())["revision_id"]
        self.prepare("B", context={"new_source": "changed"})
        with self.assertRaisesRegex(ContractError, "request changed"):
            self.store.save_result("B", {"summary": "old"}, "Old fusion", {
                "status": "PASS", "expected_stage_revisions": {},
                "expected_request_revision": request_revision})
        self.assertIsNone(self.store.latest("B"))

    def test_result_compare_and_swap_rejects_superseded_upstream(self):
        old = self.save("B")
        self.prepare("C")
        new = self.save("B", summary="new source")
        with self.assertRaisesRegex(ContractError, "Upstream revisions changed"):
            self.store.save_result("C", {"summary": "stale"}, "Stale verdict", {
                "status": "PASS", "expected_stage_revisions": {"B": old["revision_id"]}})
        self.assertIsNone(self.store.latest("C"))
        self.assertEqual(self.store.latest("B")["revision_id"], new["revision_id"])

    def test_result_compare_and_swap_rejects_failed_upstream(self):
        source = self.save("B", status="FAIL")
        self.prepare("C")
        with self.assertRaisesRegex(ContractError, "Upstream revisions changed"):
            self.store.save_result("C", {}, "Unsupported verdict", {
                "status": "PASS", "expected_stage_revisions": {"B": source["revision_id"]}})

    def test_successful_result_atomically_revokes_only_downstream_and_release(self):
        records = {stage: self.save(stage) for stage in ("B", "C", "D")}
        release = self.store.write_release("QA passed", "Final verdict", {"status": "PASS"})
        changed = self.save("C", summary="new verdict")
        self.assertEqual(self.store.latest("B")["revision_id"], records["B"]["revision_id"])
        self.assertEqual(self.store.latest("C")["revision_id"], changed["revision_id"])
        self.assertIsNone(self.store.latest("D"))
        self.assertIsNone(self.index()["release"]["latest"])
        self.assertTrue(Path(records["D"]["result_path"]).is_file())
        self.assertTrue(Path(release["final_path"]).is_file())
        self.assertTrue(self.index()["stages"]["D"]["events"])

    def test_credential_fields_rejected_but_env_names_preserved(self):
        for value in ({"OPENAI_API_KEY": "sensitive"}, {"nested": {"authorization": "Bearer value"}}):
            with self.subTest(value=list(value)), self.assertRaises(ContractError):
                self.prepare(context=value)
        self.prepare(context={"api_key_env": "OPENAI_API_KEY", "token_count": 30})
        with self.assertRaises(ContractError):
            self.prepare(prompt="Credential sk-" + "x" * 30)

    def test_non_json_values_and_unknown_status_rejected(self):
        with self.assertRaises(ContractError):
            self.prepare(context={"invalid": float("nan")})
        self.prepare()
        with self.assertRaises(ContractError):
            self.store.save_result("B", {}, "report", {"status": "MAYBE"})


if __name__ == "__main__":
    unittest.main()
