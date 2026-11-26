import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from backend.storage import Database, StorageConflict
from backend.worker import Lease, Queue, Worker


class DurableQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "platform.db"
        self.db = Database(self.path)
        self.db.migrate()
        with self.db.transaction(write=True) as repo:
            self.project = repo.create_project("A1", "brief/A1")
        self.queue = Queue(self.db)

    def state(self, run):
        with self.db.transaction() as repo:
            return repo.get_run(self.project, run)

    def test_one_claim_under_race_fifo_and_idempotent_enqueue(self):
        first = self.queue.enqueue(self.project, "one", {}, {})
        self.assertEqual(self.queue.enqueue(self.project, "one", {}, {}), first)
        second = self.queue.enqueue(self.project, "two", {}, {})
        with ThreadPoolExecutor(max_workers=4) as pool:
            leases = list(pool.map(lambda _: Queue(Database(self.path)).claim(), range(4)))
        owners = [lease for lease in leases if lease]
        self.assertEqual(len(owners), 1)
        self.assertEqual(owners[0].run_id, first)
        self.assertEqual(self.state(second)["status"], "queued")
        self.queue.release(owners[0], "request_approval")
        self.assertEqual(self.queue.claim().run_id, second)

    def test_before_and_after_checkpoint_match_operation(self):
        run = self.queue.enqueue(self.project, "one", {}, {})
        lease = self.queue.claim()
        self.queue.start_step(lease, "S1", "Dev", 1, [], {"operation_id": "OP", "input_commit": "base"})
        with self.assertRaises(StorageConflict):
            self.queue.start_step(lease, "S2", "Dev", 1, [], {"operation_id": "OP2"})
        with self.assertRaises(StorageConflict):
            self.queue.finish_step(lease, "S1", "succeeded", [], {"operation_id": "different"})
        with self.assertRaises(StorageConflict):
            self.queue.release(lease, "final_checks_passed")
        with self.assertRaises(StorageConflict):
            self.queue.heartbeat(Lease(lease.project_id, run, "fake"))
        self.queue.finish_step(lease, "S1", "succeeded", ["A1"], {"operation_id": "OP", "output_commit": "new"})
        self.queue.release(lease, "request_approval")
        saved = json.loads(self.state(run)["checkpoint_json"])
        self.assertEqual(saved, {"operation_id": "OP", "input_commit": "base", "output_commit": "new",
                                 "step_id": "S1", "phase": "after"})
        with self.db.transaction() as repo:
            read = repo.for_run(self.project, run)
            self.assertEqual(read.records("agent_steps")[0]["status"], "succeeded")
            self.assertEqual([e["event_type"] for e in read.events_after()],
                             ["claimed", "step_started", "step_finished", "request_approval"])

    def test_separate_worker_process_exit_preserves_uncertain_step(self):
        run = self.queue.enqueue(self.project, "one", {}, {})
        code = (
            "import sys,os; from backend.storage import Database; from backend.worker import Queue\n"
            "q=Queue(Database(sys.argv[1])); lease=q.claim(); "
            "q.start_step(lease,'S1','Dev',1,[],{'operation_id':'OP'}); os._exit(73)"
        )
        process = subprocess.run([sys.executable, "-c", code, str(self.path)], timeout=15)
        self.assertEqual(process.returncode, 73)
        old_token = self.state(run)["worker_lease"]
        # Deterministically advance the stored expiry, leaving the durable step and operation unchanged.
        with closing(sqlite3.connect(self.path)) as seed, seed:
            seed.execute("UPDATE runs SET lease_expires_at=datetime('now','-1 minute') WHERE id=?", (run,))
        restarted = Queue(Database(self.path))
        self.assertIsNone(restarted.claim())
        after = self.state(run)
        self.assertEqual(after["status"], "pending_recovery")
        self.assertEqual(json.loads(after["checkpoint_json"])["phase"], "before")
        self.assertIsNone(after["worker_lease"])
        with self.assertRaises(StorageConflict):
            restarted.heartbeat(Lease(self.project, run, old_token))
        with self.db.transaction() as repo:
            view = repo.for_run(self.project, run)
            self.assertEqual(len(view.records("agent_steps")), 1)
            self.assertEqual(view.events_after()[-1]["event_type"], "lease_expired")

    def test_heartbeat_renews_during_blocked_handler(self):
        run = self.queue.enqueue(self.project, "one", {}, {})
        ready, finished = threading.Event(), threading.Event()
        def handle(lease, lost):
            ready.set()
            if not finished.wait(8) or lost.is_set():
                raise RuntimeError("worker did not retain ownership")
            return "final_checks_passed"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(Worker(self.queue, handle, lease_seconds=2).run_one)
            try:
                self.assertTrue(ready.wait(3))
                first_expiration = self.state(run)["lease_expires_at"]
                deadline = time.monotonic() + 4
                while self.state(run)["lease_expires_at"] <= first_expiration:
                    if time.monotonic() >= deadline:
                        self.fail("heartbeat never extended the lease")
                    time.sleep(0.1)
                self.assertIsNone(self.queue.claim())
            finally:
                finished.set()
            self.assertTrue(future.result(timeout=3))
        self.assertEqual(self.state(run)["status"], "completed")

    def test_handler_exception_moves_run_to_recovery_without_replay(self):
        run = self.queue.enqueue(self.project, "one", {}, {})
        def fail(lease, lost):
            self.queue.start_step(lease, "S1", "Dev", 1, [], {"operation_id": "uncertain"})
            raise RuntimeError("unexpected stop")
        with self.assertRaises(RuntimeError):
            Worker(self.queue, fail).run_one()
        self.assertEqual(self.state(run)["status"], "pending_recovery")
        self.assertIsNone(self.queue.claim())
