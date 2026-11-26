"""Component compatibility probe before adding the production queue and worker."""

import multiprocessing
import sqlite3
import tempfile
import unittest
from contextlib import closing
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class Submission(BaseModel):
    brief: str = Field(min_length=1)


def build_probe_api(database: Path) -> FastAPI:
    api = FastAPI()

    @api.post("/jobs", status_code=202)
    def submit(submission: Submission):
        with closing(sqlite3.connect(database)) as connection, connection:
            row = connection.execute(
                "INSERT INTO jobs(brief, status) VALUES (?, 'queued')",
                (submission.brief,),
            )
            return {"job_id": row.lastrowid}

    return api


def process_one_pending_job(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            """UPDATE jobs SET status = 'done' WHERE id = (
                SELECT id FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1
            )"""
        )


class StackCompatibilityTest(unittest.TestCase):
    def test_request_finishes_before_separate_worker_reads_the_job(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "probe.sqlite3"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    "CREATE TABLE jobs(id INTEGER PRIMARY KEY, brief TEXT, status TEXT)"
                )

            with TestClient(build_probe_api(database)) as client:
                self.assertEqual(client.post("/jobs", json={"brief": ""}).status_code, 422)
                submitted = client.post("/jobs", json={"brief": "Create a task list"})
                self.assertEqual(submitted.status_code, 202)
                job_id = submitted.json()["job_id"]

            def read_jobs():
                with closing(sqlite3.connect(database)) as connection:
                    return connection.execute("SELECT id, brief, status FROM jobs").fetchall()

            self.assertEqual(read_jobs(), [(job_id, "Create a task list", "queued")])
            worker = multiprocessing.get_context("spawn").Process(
                target=process_one_pending_job, args=(database,)
            )
            worker.start()
            try:
                worker.join(timeout=30)
                self.assertEqual(worker.exitcode, 0)
            finally:
                if worker.is_alive():
                    worker.terminate()
                    worker.join()
                worker.close()
            self.assertEqual(read_jobs(), [(job_id, "Create a task list", "done")])
            print(
                f"fastapi={version('fastapi')} pydantic={version('pydantic')} "
                f"sqlite={sqlite3.sqlite_version} invalid=422 submitted=202 queued->done"
            )
