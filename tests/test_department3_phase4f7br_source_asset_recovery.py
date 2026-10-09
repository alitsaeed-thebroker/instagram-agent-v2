from pathlib import Path

from src.department3.phase4f7br_source_asset_recovery import (
    _category_from_text,
    recover,
)


def test_category_inference_from_original_path():
    assert _category_from_text("Beverly Hills/masterplan/site-plan.png") == "masterplan"
    assert _category_from_text("Beverly Hills/interior/living-room.jpg") == "interior"


def test_recovery_reads_project_local_input_only(tmp_path):
    project_dir = tmp_path / "input" / "Beverly Hills" / "exterior"
    project_dir.mkdir(parents=True)

    image = project_dir / "tower-exterior.jpg"
    image.write_bytes(b"fake-image-bytes")

    document = tmp_path / "input" / "Beverly Hills" / "Beverly Hills Catalogue.pdf"
    document.write_bytes(b"%PDF-fake")

    path, payload = recover(tmp_path, "Beverly Hills")

    assert path.is_file()
    assert payload["metrics"]["assets_recovered"] == 1
    assert payload["assets"][0]["category"] == "exterior"
    assert payload["source_policy"]["simulation_allowed"] is False
    assert payload["source_policy"]["original_input_only"] is True
