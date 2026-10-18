"""The demo's tutorial library and the endpoints the page is built on."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.api import main  # noqa: E402
from app.api.library import Library, match_score, _words  # noqa: E402
from tests._paths import ENGLISH_SCRIPT, TAMIL_SCRIPT  # noqa: E402


def _library(folder: str) -> Library:
    os.makedirs(os.path.join(folder, "more"))
    shutil.copy(ENGLISH_SCRIPT, os.path.join(folder, "Timed-script-sample-english.docx"))
    shutil.copy(TAMIL_SCRIPT, os.path.join(folder, "Tamil-script-sample.docx"))
    for name in ("Overview-of-Synfig-English.webm", "Overview-of-Synfig-Tamil.webm",
                 "more/Unrelated-Topic-English.webm"):
        open(os.path.join(folder, name), "wb").close()
    return Library(folder, os.path.join(folder, "thumbs"))


def test_titles_match_videos_despite_different_file_names():
    words = _words("Table and table properties")
    assert match_score(words, _words("Tables-and-table-properties-in-Writer-English")) == 1.0
    assert match_score(_words("Introduction to LibreOffice Writer"),
                       _words("Introduction-to-LibreOffice-Writer-English")) == 1.0
    assert match_score(words, _words("Viewing-and-printing-a-document-in-Writer-English")) < 0.5


def test_only_english_inputs_are_offered_and_paired():
    with tempfile.TemporaryDirectory() as folder:
        library = _library(folder)
        tutorials = library.tutorials()
        # The Tamil script and the Tamil dub are evaluation material, not inputs.
        assert [t.title for t in tutorials] == ["Overview and Installation of Synfig"]
        assert tutorials[0].video == "Overview-of-Synfig-English.webm"
        assert "Overview-of-Synfig-Tamil.webm" not in library.english_videos()
        assert os.path.join("more", "Unrelated-Topic-English.webm") in library.english_videos()


def test_sample_paths_cannot_escape_the_samples_folder():
    with tempfile.TemporaryDirectory() as folder:
        library = _library(folder)
        assert library.resolve("Timed-script-sample-english.docx")
        for bad in ("../secret.txt", os.path.abspath(__file__), "missing.docx"):
            try:
                library.resolve(bad)
            except ValueError:
                continue
            raise AssertionError(f"{bad} resolved")


def test_languages_voices_and_library_endpoints():
    client = TestClient(main.app)
    languages = client.get("/api/languages", params={"pace": 0.9}).json()["languages"]
    codes = [l["code"] for l in languages]
    assert {"ta", "hi", "te", "kn", "ml", "bn", "gu", "pa", "or", "mr"} == set(codes)
    assert all(l["name"] != l["code"] for l in languages)

    voices = client.get("/api/voices").json()
    ids = {v["id"]: v for v in voices["voices"]}
    assert len(ids) == 37 and ids["shubh"]["gender"] == "male" and ids["ishita"]["gender"] == "female"

    titles = [t["title"] for t in client.get("/api/library").json()["tutorials"]]
    assert "Overview and Installation of Synfig" in titles

    bad = client.post("/api/jobs", data={"sample_script": "Timed-script-sample-english.docx",
                                         "language": "xx", "translator": "echo", "tts": "silent"})
    assert bad.status_code == 400
    escape = client.post("/api/jobs", data={"sample_script": "../README.md", "language": "ta",
                                            "translator": "echo", "tts": "silent"})
    assert escape.status_code == 400


def test_the_original_video_is_served_only_from_allowed_places():
    with tempfile.TemporaryDirectory() as out:
        main.JOBS_DIR = os.path.abspath(out)
        client = TestClient(main.app)
        job = main.Job(id="orig", script_name="s.docx", language="ta", translator="echo",
                       tts="silent", aligner="clip-bounds", status="done")
        os.makedirs(job.folder)
        inside = os.path.join(job.folder, "upload.webm")
        with open(inside, "wb") as handle:
            handle.write(b"video")
        main.JOBS[job.id] = job

        job.video_path = inside
        assert client.get("/api/jobs/orig/original").content == b"video"
        job.video_path = os.path.abspath(__file__)  # outside the job and samples/
        assert client.get("/api/jobs/orig/original").status_code == 404
        job.video_path = None
        assert client.get("/api/jobs/orig/original").status_code == 404
        del main.JOBS[job.id]
