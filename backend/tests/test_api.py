"""Tests for the HTTP API behind the review page, on the stub providers."""

from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.api import main  # noqa: E402

STUBS = {"translator": "echo", "tts": "silent", "duration": "663.2", "workers": "1"}


def _wait(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 120
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_a_job_runs_and_a_segment_can_be_rewritten():
    with tempfile.TemporaryDirectory() as out:
        main.JOBS_DIR = os.path.abspath(out)
        client = TestClient(main.app)

        assert client.get("/").status_code == 200
        health = client.get("/api/health").json()
        assert {"indictrans+sarvam", "sarvam", "indictrans+groq"} <= set(health["translators"])
        assert "Timed-script-sample-english.docx" in client.get("/api/samples").json()["scripts"]

        created = client.post(
            "/api/jobs",
            data={"sample_script": "Timed-script-sample-english.docx", "language": "ta", **STUBS},
        )
        assert created.status_code == 200, created.text
        job = _wait(client, created.json()["id"])
        assert job["status"] == "done", job["error"]
        assert job["aligner"] == "clip-bounds"  # silence pairs with the stub aligner
        assert set(job["stubs"]) >= {"echo", "silent"}
        assert job["progress"]["synthesize"] == [95, 95]

        track = client.get(f"/api/jobs/{job['id']}/track").json()
        assert len(track["rows"]) == 95
        assert any(name.endswith("-dub.wav") for name in track["exports"])
        first = track["rows"][0]
        assert client.get(first["audio"]).status_code == 200

        # The reviewer rewrites one segment; only that one changes.
        target = track["rows"][3]["id"]
        edited = client.post(f"/api/jobs/{job['id']}/segments/{target}", json={"text": "Short."})
        assert edited.status_code == 200, edited.text
        rows = {r["id"]: r for r in edited.json()["rows"]}
        assert rows[target]["text"] == "Short."
        assert rows[target]["translator"] == "manual"
        assert rows[target]["fitted"] is True
        before = {r["id"]: r["text"] for r in track["rows"]}
        assert all(rows[k]["text"] == before[k] for k in before if k != target)


def test_files_outside_the_job_are_not_served():
    with tempfile.TemporaryDirectory() as out:
        main.JOBS_DIR = os.path.abspath(out)
        main.JOBS["x"] = main.Job(id="x", script_name="s", language="ta",
                                  translator="echo", tts="silent", aligner="clip-bounds")
        client = TestClient(main.app)
        assert client.get("/api/jobs/x/files/..%2F..%2Fsecret.txt").status_code == 404


def test_unknown_providers_are_rejected_before_a_job_starts():
    client = TestClient(main.app)
    response = client.post(
        "/api/jobs",
        data={"sample_script": "Timed-script-sample-english.docx", "tts": "nonexistent"},
    )
    assert response.status_code == 400
