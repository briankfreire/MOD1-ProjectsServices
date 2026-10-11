import shutil
import tarfile
import zipfile
from pathlib import Path

from hatchling.builders.sdist import SdistBuilder
from hatchling.builders.wheel import WheelBuilder


def test_distributions_exclude_runtime_secrets_and_private_artifacts(tmp_path):
    source = Path(__file__).resolve().parents[1]
    for name in ("pyproject.toml", "README.md", "uv.lock"):
        shutil.copyfile(source / name, tmp_path / name)
    shutil.copytree(source / "src", tmp_path / "src")
    for name in (".env", ".local/proof.json", ".superpowers/progress.md"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic-private-marker", encoding="utf-8")
    (tmp_path / ".env.example").write_text("PUBLIC_CONFIGURATION_EXAMPLE", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    sdist = next(SdistBuilder(str(tmp_path)).build(directory=str(dist), versions=["standard"]))
    wheel = next(WheelBuilder(str(tmp_path)).build(directory=str(dist), versions=["standard"]))
    with tarfile.open(dist / sdist) as archive:
        names = archive.getnames()
        assert any(name.endswith("/.env.example") for name in names)
    with zipfile.ZipFile(dist / wheel) as archive:
        names += archive.namelist()
    assert not any(
        Path(name).name == ".env" or "/.local/" in name or "/.superpowers/" in name
        for name in names
    )
