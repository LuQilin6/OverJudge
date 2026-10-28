"""A report revisions serialize with downstream commits and publication.

All recordings and review attestations are synthetic software fixtures. The
threads exercise artifact ordering, not whether anybody actually watched video.
"""

from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from overjudge.contracts import POV_IDS, read_json
from overjudge.pipeline import DownstreamPipeline
from overjudge import stage_a
from tests.downstream_support import b_response, c_response, d_response, import_response
from tests.test_integrated_pipeline import integrated_project, submit_synthetic_report


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires real FFmpeg tools")
class ConcurrentNativeHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.service = integrated_project(self.root)
        self.records = {
            pov: submit_synthetic_report(self.service, pov) for pov in POV_IDS
        }
        self.service.export_handoff()
        self.pipeline = DownstreamPipeline(self.service.config_path, self.root)

    def tearDown(self):
        self.temp.cleanup()

    def _import_and_replace_a(self, stage, response, request, commit_method):
        """Start an A writer while the downstream commit holds its source guard."""
        commit_entered = threading.Event()
        writer_attempted_lock = threading.Event()
        writer_acquired_lock = threading.Event()
        resume_commit = threading.Event()
        errors = []
        results = {}
        original_lock = stage_a.file_lock
        original_commit = getattr(self.pipeline.store, commit_method)
        a_lock_path = self.service.output / ".stage_a_index.lock"

        @contextmanager
        def observed_a_lock(path):
            is_writer = (
                threading.current_thread().name == "stage-a-writer"
                and Path(path) == a_lock_path
            )
            if is_writer:
                writer_attempted_lock.set()
            with original_lock(path):
                if is_writer:
                    writer_acquired_lock.set()
                yield

        def paused_commit(*args, **kwargs):
            commit_entered.set()
            if not resume_commit.wait(10):
                raise AssertionError("Test did not release the downstream commit barrier")
            return original_commit(*args, **kwargs)

        def downstream_worker():
            try:
                results["downstream"] = import_response(
                    self.pipeline, stage, request, response, accept_limitations=True,
                )
            except BaseException as exc:
                errors.append(("downstream", exc))

        def upstream_worker():
            try:
                results["upstream"] = submit_synthetic_report(
                    self.service, "tank", reviewer="Concurrent replacement synthetic review",
                    job=self.records["tank"]["job_path"],
                )
            except BaseException as exc:
                errors.append(("upstream", exc))

        importer = threading.Thread(target=downstream_worker, name="downstream-import", daemon=True)
        writer = threading.Thread(target=upstream_worker, name="stage-a-writer", daemon=True)
        writer_was_blocked = False
        try:
            with patch("overjudge.stage_a.file_lock", observed_a_lock), patch.object(
                self.pipeline.store, commit_method, paused_commit,
            ):
                importer.start()
                self.assertTrue(commit_entered.wait(10), f"Import did not reach {commit_method}: {errors}")
                writer.start()
                self.assertTrue(writer_attempted_lock.wait(10), f"A submit did not reach its index lock: {errors}")
                # The writer has definitely attempted the real lock. It must be
                # unable to acquire it until the import/release commit finishes.
                writer_was_blocked = not writer_acquired_lock.wait(0.15)
                resume_commit.set()
                importer.join(10)
                writer.join(10)
        finally:
            resume_commit.set()
            if importer.ident is not None:
                importer.join(10)
            if writer.ident is not None:
                writer.join(10)
        self.assertFalse(importer.is_alive(), "Downstream commit deadlocked")
        self.assertFalse(writer.is_alive(), "A submit deadlocked")
        self.assertTrue(writer_was_blocked, "A revision interleaved with a downstream commit/publication")
        self.assertEqual(errors, [], repr(errors))
        self.assertTrue(writer_acquired_lock.is_set())
        self.assertEqual(results["downstream"]["status"], "PASS_WITH_LIMITATIONS")
        self.assertNotEqual(results["upstream"]["revision_id"], self.records["tank"]["revision_id"])
        # Do not call pipeline.status(): that would independently detect stale A
        # and conceal a failure to revoke descendants in A submit's own lock.
        self.assertIsNone(self.pipeline.store.latest("B"))
        self.assertIsNone(read_json(self.pipeline.store.metadata_path)["release"]["latest"])
        return results["downstream"]

    def test_a_revision_waits_for_b_commit_then_atomically_revokes_b(self):
        request = self.pipeline.prepare("B", accept_limitations=True)["request_path"]
        imported = self._import_and_replace_a("B", b_response(), request, "save_result")
        self.assertTrue(Path(imported["record"]["report_path"]).is_file())
        self.assertIsNone(self.pipeline.store.latest("C"))
        self.assertIsNone(self.pipeline.store.latest("D"))

    def test_a_revision_waits_through_d_publication_then_revokes_release(self):
        for stage, response in (("B", b_response()), ("C", c_response())):
            request = self.pipeline.prepare(stage, accept_limitations=True)["request_path"]
            import_response(self.pipeline, stage, request, response, accept_limitations=True)
        request = Path(self.pipeline.prepare("D", accept_limitations=True)["request_path"])
        clips = read_json(request / "clip_index.json")["clips"]
        imported = self._import_and_replace_a("D", d_response(clips), request, "write_release")
        self.assertTrue(imported["release"]["published"])
        self.assertTrue(Path(imported["release"]["final_path"]).is_file(), "Released history must remain inspectable")
        self.assertIsNone(self.pipeline.store.latest("D"))


if __name__ == "__main__":
    unittest.main()
