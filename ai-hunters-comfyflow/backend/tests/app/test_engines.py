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


ENV = {"python_version": "cp312", "os": "win", "platform_tag": "win_amd64", "torch": "2.8.0+cu128", "cuda": "12.8",
       "cxx11abi": None, "pinned": {"torch": "2.8.0+cu128", "torchvision": "0.23.0+cu128", "torchaudio": None}}


def test_nunchaku_wheel_matches_python_torch_and_platform(monkeypatch):
    engine = engines.for_folder("ComfyUI-nunchaku")
    monkeypatch.setattr(engines, "_fetch_json", lambda url, local: CDN)
    monkeypatch.setattr(engines, "url_exists", lambda url: True)
    url, desc = engines._resolve_versions_list(engine, ENV, None)[0]
    assert url == "https://github.com/nunchaku-tech/nunchaku/releases/download/v1.2.0/nunchaku-1.2.0+torch2.8-cp312-cp312-win_amd64.whl"
    with pytest.raises(engines.EngineError):
        engines._resolve_versions_list(engine, {**ENV, "python_version": "cp39"}, None)


def test_newer_pytorch_than_the_engine_supports_changes_nothing(monkeypatch):
    """PyTorch 2.11 + Nunchaku built up to 2.9: no 'closest' build (it cannot load), no download, a clear answer."""
    engine = engines.for_folder("ComfyUI-nunchaku")
    monkeypatch.setattr(engines, "_fetch_json", lambda url, local: CDN)
    asked = []
    monkeypatch.setattr(engines, "url_exists", lambda url: asked.append(url) or True)
    with pytest.raises(engines.TorchUnsupported) as e:
        engines._resolve_versions_list(engine, {**ENV, "torch": "2.11.0+cu128"}, None)
    assert e.value.supported == ["2.7", "2.8", "2.9"] and "2.11" in str(e.value) and asked == []
    cmds = []
    monkeypatch.setattr(engines, "environment", lambda mods: {**ENV, "torch": "2.11.0+cu128", "modules": {"nunchaku": "0.16.1"}})
    with pytest.raises(engines.TorchUnsupported):
        engines.ensure(engine, None, cmds.append, lambda m: None)
    assert cmds == []  # nothing installed, nothing uninstalled – not even the unrelated package


def test_missing_release_files_are_skipped_before_pip(monkeypatch):
    """The newest release lacks this build (the 404s in the Setup log): the next release that has it is used."""
    engine = engines.for_folder("ComfyUI-nunchaku")
    monkeypatch.setattr(engines, "_fetch_json", lambda url, local: CDN)
    monkeypatch.setattr(engines, "url_exists", lambda url: "1.1.0" in url)
    url, _ = engines._resolve_versions_list(engine, ENV, None)[0]
    assert "/v1.1.0/nunchaku-1.1.0+torch2.8-cp312-cp312-win_amd64.whl" in url
    monkeypatch.setattr(engines, "url_exists", lambda url: False)
    with pytest.raises(engines.EngineError) as e:
        engines._resolve_versions_list(engine, ENV, None)
    assert "checked" in str(e.value)


def test_ensure_replaces_the_unrelated_pypi_package(monkeypatch):
    engine = engines.for_folder("ComfyUI-nunchaku")
    assert engine["module"] == "nunchaku"
    monkeypatch.setattr(engines, "environment", lambda mods: {**ENV, "modules": {"nunchaku": "0.16.1"}})
    monkeypatch.setattr(engines, "_fetch_json", lambda url, local: CDN)
    monkeypatch.setattr(engines, "url_exists", lambda url: True)
    cmds, logs = [], []
    assert engines.ensure(engine, None, cmds.append, logs.append) is True
    assert cmds[0][-3:] == ["uninstall", "-y", "nunchaku"]
    install = cmds[1]
    assert install[5].endswith("nunchaku-1.2.0+torch2.8-cp312-cp312-win_amd64.whl")  # python -m pip install --disable… <wheel>
    pins = open(install[install.index("-c") + 1], encoding="utf-8").read()
    assert "torch==2.8.0+cu128" in pins and "torchvision==0.23.0+cu128" in pins  # PyTorch cannot be replaced
    monkeypatch.setattr(engines, "environment", lambda mods: {**ENV, "modules": {"nunchaku": "1.2.0"}})
    cmds.clear()
    assert engines.ensure(engine, None, cmds.append, logs.append) is False and cmds == []


ASSETS = [  # real naming styles of the projects in node-engines.json
    "sageattention-2.2.0+cu128torch2.8.0.post3-cp39-abi3-win_amd64.whl",
    "sageattention-2.2.0+cu128torch2.7.1.post3-cp39-abi3-win_amd64.whl",
    "sageattention-2.2.0+cu126torch2.8.0.post3-cp39-abi3-win_amd64.whl",
    "sageattention-2.2.0+cu130torch2.9.0.post3-cp39-abi3-win_amd64.whl",
    "flash_attn-2.8.3+cu128torch2.8.0cxx11abiFALSE-cp312-cp312-win_amd64.whl",
    "flash_attn-2.8.3+cu12torch2.8cxx11abiTRUE-cp312-cp312-linux_x86_64.whl",
    "flash_attn-2.8.3+cu12torch2.8cxx11abiFALSE-cp312-cp312-linux_x86_64.whl",
    "flash_attn-2.8.3+cu128torch2.8.0cxx11abiFALSE-cp311-cp311-win_amd64.whl",
]


def _assets(prefix):
    return [{"name": n, "url": f"https://x/{n}"} for n in ASSETS if n.startswith(prefix)]


def test_wheel_file_names_are_understood():
    w = engines.parse_wheel(ASSETS[0])
    assert (w["torch"], w["cuda"], w["py"], w["abi"], w["plat"]) == ("2.8", "12.8", "cp39", "abi3", "win_amd64")
    lw = engines.parse_wheel(ASSETS[5])
    assert (lw["cuda"], lw["cxx11abi"]) == ("12", True)


def test_the_matching_wheel_is_chosen():
    assert engines.choose_wheel(_assets("sage"), ENV)["name"] == ASSETS[0]  # exact CUDA beats cu126; abi3 on cp312
    assert engines.choose_wheel(_assets("sage"), {**ENV, "cuda": "12.6"})["name"] == ASSETS[2]  # never newer CUDA
    assert engines.choose_wheel(_assets("sage"), {**ENV, "torch": "2.6.0"}) is None  # torch must match
    assert engines.choose_wheel(_assets("sage"), {**ENV, "cuda": None}) is None  # CPU PyTorch
    assert engines.choose_wheel(_assets("flash"), ENV)["name"] == ASSETS[4]  # cp312, not cp311
    linux = {**ENV, "os": "linux", "platform_tag": "linux_x86_64", "cxx11abi": True}
    assert engines.choose_wheel(_assets("flash"), linux)["name"] == ASSETS[5]  # matching C++ ABI


def test_github_release_resolver_reports_what_exists(monkeypatch):
    monkeypatch.setattr(engines, "github_assets", lambda repo, releases=15: [{**a, "release": "v2.2.0", "prerelease": False} for a in _assets("sage")])
    engine = engines.load()["sageattention"]
    [(url, desc)] = engines._resolve_github_release(engine, ENV, None)
    assert url.endswith(ASSETS[0]) and "woct0rdho/SageAttention" in desc
    with pytest.raises(engines.TorchUnsupported) as e:
        engines._resolve_github_release(engine, {**ENV, "torch": "2.5.1"}, None)
    assert "2.8" in e.value.supported
    with pytest.raises(engines.EngineError):
        engines._resolve_github_release(engine, {**ENV, "os": "linux", "platform_tag": "linux_x86_64"}, None)  # no Linux repo


def test_pip_by_torch_picks_the_version_for_this_pytorch():
    engine = engines.load()["triton"]
    assert engines._resolve_pip_by_torch(engine, ENV, None)[0][0] == "triton-windows>=3.4,<3.5"
    assert engines._resolve_pip_by_torch(engine, {**ENV, "os": "linux"}, None)[0][0] == "triton>=3.4,<3.5"


def test_missing_module_fix_never_pip_installs_an_engine():
    from app.services import fixes

    fix = fixes.match("NunchakuFluxDiTLoader (ID 3) failed: ModuleNotFoundError No module named 'nunchaku'")
    assert fix["actions"] == [{"type": "engine", "args": ["nunchaku"]}] and "unrelated library" in fix["explain"]


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
