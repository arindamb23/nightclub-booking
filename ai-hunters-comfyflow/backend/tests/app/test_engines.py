"""Custom nodes that install but fail to load (ComfyUI-nunchaku without its 'nunchaku' engine)."""
from pathlib import Path

import pytest

from app.services import engines, nodepacks

LOG = (Path(__file__).parent.parent / "data" / "comfyui_nunchaku.log").read_text(encoding="utf-8")


def test_import_failures_are_read_from_the_comfyui_log():
    f = nodepacks.import_failures(LOG)
    assert f["comfyui-nunchaku"]["modules"] == ["nunchaku"]
    assert "No module named 'nunchaku'" in f["comfyui-nunchaku"]["errors"][0]
    assert f["comfyui-bar"]["modules"] == ["sageattention"]  # ComfyUI's own "Cannot import ..." line
    assert "cannot import name" in f["comfyui-foo"]["errors"][0]  # a traceback with [INFO] prefixes
    assert "rgthree-comfy" not in f



@pytest.fixture
def nunchaku_installed_folder(monkeypatch):
    real = nodepacks.import_failures.__code__
    monkeypatch.setattr(nodepacks, "_installed_folders", lambda: {"comfyui-nunchaku"})
    monkeypatch.setattr(nodepacks, "_manager_map", lambda: {"exact": {"NunchakuFluxDiTLoader": [
        {"url": "https://github.com/nunchaku-tech/ComfyUI-nunchaku", "name": "ComfyUI-nunchaku"}]}, "patterns": []})
    monkeypatch.setattr(nodepacks, "_stars", lambda: {})
    return real


def test_pack_that_failed_to_load_is_broken(client, monkeypatch, nunchaku_installed_folder):
    parsed = nodepacks.import_failures(LOG)
    monkeypatch.setattr(nodepacks, "import_failures", lambda log_text=None: parsed)
    pack = nodepacks.resolve_packs(["NunchakuFluxDiTLoader"])[0]
    assert pack["status"] == "broken" and pack["missing_modules"] == ["nunchaku"]
    assert "could not load it" in pack["error"]


CDN = {
    "versions": ["1.2.0", "1.1.0"], "supported_python": ["cp310", "cp311", "cp312", "cp313"],
    "supported_torch": ["torch2.7", "torch2.8", "torch2.9"],
    "filename_template": "nunchaku-{version}+{torch_version}-{python_version}-{python_version}-{platform}.whl",
    "url_templates": {"github": "https://github.com/nunchaku-tech/nunchaku/releases/download/{version_tag}/{filename}"},
}


def test_nunchaku_wheel_matches_python_torch_and_platform():
    w = engines.nunchaku_wheel(CDN, {"python_version": "cp312", "platform_tag": "win_amd64", "torch": "2.8.0+cu128"})
    assert w["name"] == "nunchaku-1.2.0+torch2.8-cp312-cp312-win_amd64.whl" and w["exact_torch"] == "True"
    assert w["url"] == "https://github.com/nunchaku-tech/nunchaku/releases/download/v1.2.0/nunchaku-1.2.0+torch2.8-cp312-cp312-win_amd64.whl"
    newer = engines.nunchaku_wheel(CDN, {"python_version": "cp312", "platform_tag": "win_amd64", "torch": "2.10.1+cu130"})
    assert newer["torch"] == "torch2.9" and newer["exact_torch"] == "False"  # closest lower, like the pack's installer
    with pytest.raises(engines.EngineError):
        engines.nunchaku_wheel(CDN, {"python_version": "cp39", "platform_tag": "win_amd64", "torch": "2.8.0"})


def test_ensure_replaces_the_unrelated_pypi_package(monkeypatch):
    engine = engines.for_folder("ComfyUI-nunchaku")
    assert engine["module"] == "nunchaku"
    monkeypatch.setattr(engines, "environment", lambda mods: {"python_version": "cp312", "platform_tag": "win_amd64",
                                                             "torch": "2.8.0", "modules": {"nunchaku": "0.16.1"}})
    monkeypatch.setattr(engines, "_versions_config", lambda e, d: CDN)
    cmds, logs = [], []
    assert engines.ensure(engine, None, cmds.append, logs.append) is True
    assert cmds[0][-3:] == ["uninstall", "-y", "nunchaku"]
    assert cmds[1][-1].endswith("nunchaku-1.2.0+torch2.8-cp312-cp312-win_amd64.whl")
    # a real engine is left alone
    monkeypatch.setattr(engines, "environment", lambda mods: {"python_version": "cp312", "platform_tag": "win_amd64",
                                                             "torch": "2.8.0", "modules": {"nunchaku": "1.2.0"}})
    cmds.clear()
    assert engines.ensure(engine, None, cmds.append, logs.append) is False and cmds == []


def test_missing_module_fix_never_pip_installs_an_engine():
    from app.services import fixes

    fix = fixes.match("NunchakuFluxDiTLoader (ID 3) failed: ModuleNotFoundError No module named 'nunchaku'")
    assert fix["actions"] == [{"type": "engine", "args": ["nunchaku"]}]


def test_settings_health_lists_broken_packs_and_repairs_them(client, monkeypatch):
    folder = nodepacks.custom_nodes_dir() / "ComfyUI-nunchaku"
    (folder / ".git").mkdir(parents=True, exist_ok=True)
    (folder / ".git" / "config").write_text('[core]\n\tbare = false\n[remote "origin"]\n\turl = https://github.com/nunchaku-tech/ComfyUI-nunchaku.git\n', encoding="utf-8")
    parsed = nodepacks.import_failures(LOG)
    monkeypatch.setattr(nodepacks, "import_failures", lambda log_text=None: parsed)
    h = client.get("/api/nodepacks/health").json()
    pack = next(p for p in h["packs"] if p["folder"] == "ComfyUI-nunchaku")
    assert pack["url"] == "https://github.com/nunchaku-tech/ComfyUI-nunchaku" and pack["modules"] == ["nunchaku"]
    assert pack["engine"].startswith("Nunchaku engine")
    started = []
    monkeypatch.setattr(nodepacks, "install", lambda url, class_types=None, name="": started.append(url) or {"url": url, "status": "queued"})
    assert client.post("/api/nodepacks/repair", json={"folder": "ComfyUI-nunchaku"}).json()["status"] == "queued"
    assert started == ["https://github.com/nunchaku-tech/ComfyUI-nunchaku"]
    assert client.post("/api/nodepacks/repair", json={"folder": "../etc"}).status_code == 400
