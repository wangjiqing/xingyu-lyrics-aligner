from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_bundles_and_validates_nltk_punkt_tab() -> None:
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "NLTK_DATA=/usr/local/share/nltk_data" in dockerfile
    assert "raw.githubusercontent.com/nltk/nltk_data/gh-pages" in dockerfile
    assert "e57f64187974277726a3417ca6f181ec5403676c717672eef6a748a7b20e0106" in dockerfile
    assert "ZipFile('/tmp/punkt_tab.zip').extractall('${NLTK_DATA}/tokenizers')" in dockerfile
    assert "nltk.data.find('tokenizers/punkt_tab/english/')" in dockerfile
    assert 'chmod -R a+rX "${NLTK_DATA}"' in dockerfile


def test_container_entrypoint_does_not_download_nltk_data_at_runtime() -> None:
    entrypoint = (REPOSITORY_ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")

    assert "nltk.download" not in entrypoint
    assert "nltk.downloader" not in entrypoint
