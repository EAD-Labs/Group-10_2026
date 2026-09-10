"""Tests for the FastAPI wrapper in app/api.py.

These exercise the HTTP layer only - parsing and pipeline correctness are
already covered by test_parser.py and test_pipeline.py. The point here is
narrower: that the endpoints wire request -> existing function -> response
correctly, and that QAReport's derived numbers (max_drift, mean_rate_ratio,
etc.) actually survive JSON serialization - they are computed_field
properties, easy to silently drop from a response_model.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.api import app  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGLISH_SCRIPT = os.path.join(REPO_ROOT, "Timed-script-sample-english.docx")


def _upload_english() -> dict:
    client = TestClient(app)
    with open(ENGLISH_SCRIPT, "rb") as handle:
        response = client.post(
            "/api/scripts",
            files={
                "script": (
                    "Timed-script-sample-english.docx",
                    handle,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            data={"language": "en", "duration": "663.2"},
        )
    assert response.status_code == 200, response.text
    return response.json()


def test_health():
    client = TestClient(app)
    assert client.get("/api/health").json() == {"status": "ok"}


def test_upload_matches_the_cli_s_own_numbers():
    """README documents 95 segments, 11 action cues for this script - the API
    must report the same, since it calls the identical parse_script()."""
    body = _upload_english()
    script = body["script"]
    assert len(script["segments"]) == 95
    assert len(script["cues"]) == 11
    assert script["error_count"] > 0  # ParsedScript.error_count survives serialization


def test_run_reports_qa_numbers_the_readme_documents():
    """README's Step 2 table: English, echo/silent stubs -> 11/95 over budget,
    median pause 1.16s. If QAReport's computed_field properties were dropped
    from serialization, these keys would be missing entirely, not just wrong."""
    uploaded = _upload_english()
    client = TestClient(app)
    response = client.post(
        f"/api/scripts/{uploaded['id']}/run",
        json={"language": "en"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    qa = body["track"]["qa"]
    assert qa["over_budget_count"] == 11
    assert round(qa["median_pause"], 2) == 1.16
    assert body["stubbed_stages"] == ["clip-bounds", "echo", "manifest", "silent"]

    # audio_urls/export_urls are additive (not on LanguageTrack itself) so the
    # Audio and Export pages can play/download generated files directly.
    first_segment = body["track"]["translations"][0]["segment_id"]
    assert body["audio_urls"][first_segment].startswith("/media/")
    assert len(body["export_urls"]) == 2
    assert all(u.startswith("/media/") for u in body["export_urls"])

    media_response = client.get(body["audio_urls"][first_segment])
    assert media_response.status_code == 200
    assert media_response.headers["content-type"] == "audio/wave" or media_response.headers[
        "content-type"
    ].startswith("audio/")


def test_list_scripts_reflects_session_state():
    client = TestClient(app)
    uploaded = _upload_english()
    before = client.get("/api/scripts").json()
    ids = [s["id"] for s in before]
    assert uploaded["id"] in ids
    summary = next(s for s in before if s["id"] == uploaded["id"])
    assert summary["segment_count"] == 95
    assert summary["languages_run"] == []

    client.post(f"/api/scripts/{uploaded['id']}/run", json={"language": "en"})
    after = client.get("/api/scripts").json()
    summary = next(s for s in after if s["id"] == uploaded["id"])
    assert summary["languages_run"] == ["en"]


def test_run_segments_regenerates_only_the_named_segment():
    uploaded = _upload_english()
    client = TestClient(app)
    client.post(f"/api/scripts/{uploaded['id']}/run", json={"language": "en"})
    response = client.post(
        f"/api/scripts/{uploaded['id']}/run-segments",
        json={"language": "en", "segment_ids": ["S-001"]},
    )
    assert response.status_code == 200, response.text
    track = response.json()["track"]
    assert len(track["translations"]) == 95


def test_run_rejects_an_unknown_provider():
    uploaded = _upload_english()
    client = TestClient(app)
    response = client.post(
        f"/api/scripts/{uploaded['id']}/run",
        json={"language": "en", "translator": "not-a-real-translator"},
    )
    assert response.status_code == 422


def test_unknown_script_id_is_a_404():
    client = TestClient(app)
    assert client.get("/api/scripts/does-not-exist").status_code == 404
    response = client.post(
        "/api/scripts/does-not-exist/run",
        json={"language": "en"},
    )
    assert response.status_code == 404


if __name__ == "__main__":
    failures = 0
    for name, function in sorted(globals().items()):
        if not name.startswith("test_") or not callable(function):
            continue
        try:
            function()
            print(f"  PASS  {name}")
        except AssertionError as error:
            failures += 1
            print(f"  FAIL  {name}: {error}")
    print()
    print("all passed" if not failures else f"{failures} failing")
    sys.exit(1 if failures else 0)
