"""Stage A writers must not collide when preparing five POVs in parallel."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from src.artifacts import digest, file_lock, save_json
from src.contracts import ContractError


class StageAAtomicTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_parallel_manifest_writes_do_not_remove_another_writers_temp_file(self):
        path = self.root / "run" / "manifest.json"
        workers = 12
        barrier = Barrier(workers)

        def write_manifest(index):
            barrier.wait()
            for revision in range(5):
                save_json(path, {"writer": index, "revision": revision, "payload": "x" * 32000})

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(write_manifest, index) for index in range(workers)]
            for future in futures:
                future.result()
        result = json.loads(path.read_text())
        self.assertIn(result["writer"], range(workers))
        self.assertEqual(result["revision"], 4)
        self.assertEqual(result["payload"], "x" * 32000)
        self.assertEqual(list(path.parent.glob(".writing-*")), [])

    def test_file_lock_protects_whole_index_read_update(self):
        path = self.root / "stage_a_index.json"
        lock = self.root / ".stage_a_index.lock"
        save_json(path, {"count": 0})

        def update_index(_):
            for _ in range(15):
                with file_lock(lock):
                    result = json.loads(path.read_text())
                    save_json(path, {"count": result["count"] + 1})

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(update_index, range(8)))
        self.assertEqual(json.loads(path.read_text()), {"count": 120})
        self.assertEqual(list(self.root.glob(".writing-*")), [])

    def test_failed_replace_cleans_temporary_file_and_retains_previous_json(self):
        path = self.root / "manifest.json"
        save_json(path, {"status": "original"})
        with patch("src.artifacts.os.replace", side_effect=OSError("synthetic failed rename")):
            with self.assertRaises(OSError):
                save_json(path, {"status": "new"})
        self.assertEqual(json.loads(path.read_text()), {"status": "original"})
        self.assertEqual(list(self.root.glob(".writing-*")), [])

    def test_finite_json_is_required_and_digest_uses_file_bytes(self):
        path = self.root / "artifact.json"
        with self.assertRaises(ContractError):
            save_json(path, {"timestamp": float("nan")})
        self.assertFalse(path.exists())
        path.write_bytes(b"original recording")
        self.assertEqual(digest(path), hashlib.sha256(b"original recording").hexdigest())


if __name__ == "__main__":
    unittest.main()
