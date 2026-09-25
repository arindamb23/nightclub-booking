"""Missing custom nodes: detection, where the package comes from, install, and the run guard."""
import json

import pytest

from app.services import nodepacks


@pytest.fixture
def manager_map(tmp_path, monkeypatch):
    f = tmp_path / "extension-node-map.json"
    f.write_text(json.dumps({
        "https://github.com/fork/ComfyUI-Copycat": [["UnetLoaderGGUF"], {"title_aux": "Copycat"}],
        "https://github.com/city96/ComfyUI-GGUF": [["UnetLoaderGGUF", "CLIPLoaderGGUF"], {"title_aux": "ComfyUI-GGUF"}],
        "https://github.com/kijai/ComfyUI-KJNodes": [["GetImageSizeAndCount"], {"title_aux": "KJNodes", "nodename_pattern": "^KJ"}],
    }), encoding="utf-8")
    monkeypatch.setattr(nodepacks, "_manager_map_file", lambda: f)
    monkeypatch.setattr(nodepacks, "_stars", lambda: {"https://github.com/city96/comfyui-gguf": 2500, "https://github.com/fork/comfyui-copycat": 3})
    monkeypatch.setattr(nodepacks, "_registry_repo", lambda cnr: "https://github.com/someone/registry-pack" if cnr == "reg-pack" else None)
    return f


def test_package_lookup_order(client, manager_map):
    hints = {"FancyNode": {"aux_id": "author/ComfyUI-Fancy", "cnr_id": "fancy"}, "RegNode": {"cnr_id": "reg-pack"}}
    packs = nodepacks.resolve_packs(["UnetLoaderGGUF", "CLIPLoaderGGUF", "KJWidget", "FancyNode", "RegNode", "Mystery"], hints)
    by_url = {p["url"]: p for p in packs}
    assert sorted(by_url["https://github.com/city96/ComfyUI-GGUF"]["class_types"]) == ["CLIPLoaderGGUF", "UnetLoaderGGUF"]
    assert "https://github.com/fork/ComfyUI-Copycat" not in by_url  # a fork listing the same node loses to the original
    assert by_url["https://github.com/city96/ComfyUI-GGUF"]["alternatives"] == ["https://github.com/fork/ComfyUI-Copycat"]
    assert by_url["https://github.com/kijai/ComfyUI-KJNodes"]["class_types"] == ["KJWidget"]  # nodename_pattern
    assert by_url["https://github.com/author/ComfyUI-Fancy"]["source"] == "workflow"
    assert by_url["https://github.com/someone/registry-pack"]["source"] == "Comfy Registry"
    unknown = [p for p in packs if p["status"] == "no_url"]
    assert unknown[0]["class_types"] == ["Mystery"] and packs[-1] is unknown[0]
    # what the user enters wins from then on
    nodepacks.save_user_mapping(["Mystery"], "owner/mystery-nodes")
    packs = nodepacks.resolve_packs(["Mystery"])
    assert packs[0]["url"] == "https://github.com/owner/mystery-nodes" and packs[0]["source"] == "you"


def test_hints_come_from_group_nodes_and_subgraphs():
    ui = {
        "nodes": [{"type": "A", "properties": {"aux_id": "x/a", "cnr_id": "a"}}, {"type": "KSampler", "properties": {"cnr_id": "comfy-core"}}],
        "extra": {"groupNodes": {"G": {"nodes": [{"type": "B", "properties": {"aux_id": "x/b"}}]}}},
        "definitions": {"subgraphs": [{"id": "s", "nodes": [{"type": "C", "properties": {"cnr_id": "c"}}]}]},
    }
    assert nodepacks.hints_from_source(ui) == {"A": {"aux_id": "x/a", "cnr_id": "a"}, "B": {"aux_id": "x/b"}, "C": {"cnr_id": "c"}}


def test_url_validation():
    assert nodepacks.normalize_url("owner/repo") == "https://github.com/owner/repo"
    assert nodepacks.normalize_url("https://github.com/o/r.git/") == "https://github.com/o/r"
    with pytest.raises(nodepacks.NodePackError):
        nodepacks.normalize_url("C:\\\\evil")
    assert nodepacks.repo_folder("https://github.com/o/ComfyUI-GGUF") == "ComfyUI-GGUF"


def test_run_is_blocked_until_nodes_are_installed(client, manager_map, monkeypatch, tmp_path):
    prompt = {"1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "x.gguf"}},
              "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "x"}}}
    p = tmp_path / "gguf_api.json"
    p.write_text(json.dumps(prompt), encoding="utf-8")
    with open(p, "rb") as f:
        wf = client.post("/api/workflows/upload", files={"file": ("gguf_api.json", f, "application/json")}).json()
    monkeypatch.setattr(nodepacks, "known_types", lambda refresh=True: {"SaveImage", "KSampler"})
    check = client.get(f"/api/workflows/{wf['id']}/nodes-check").json()
    assert check["available"] and check["packs"][0]["name"] == "ComfyUI-GGUF" and check["packs"][0]["status"] == "missing"
    r = client.post("/api/runs", json={"workflow_id": wf["id"]})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "nodes_missing" and detail["packs"][0]["class_types"] == ["UnetLoaderGGUF"]

    # install: git clone + requirements with ComfyUI's python, remembered for Setup.bat
    commands = []

    def fake_run(job, args, cwd=None, timeout=1800):
        commands.append(args)
        if "clone" in args:
            target = nodepacks.Path(args[-1])
            target.mkdir(parents=True)
            (target / "requirements.txt").write_text("gguf\n")
    monkeypatch.setattr(nodepacks, "_run", fake_run)
    monkeypatch.setattr(nodepacks, "_git", lambda: "git")
    monkeypatch.setattr(nodepacks, "_remember_in_setup", lambda url: commands.append(["remember", url]))
    job = client.post("/api/nodepacks/install", json={"url": "https://github.com/city96/ComfyUI-GGUF", "class_types": ["UnetLoaderGGUF"]}).json()
    assert job["status"] in ("queued", "installing")
    from tests.app.conftest import wait_for

    done = wait_for(lambda: next((j for j in client.get("/api/nodepacks/jobs").json()["jobs"] if j["status"] in ("installed", "error")), None))
    assert done["status"] == "installed", done
    assert commands[0][:3] == ["git", "clone", "--depth"] and commands[1][1:4] == ["-m", "pip", "install"]
    assert commands[-1] == ["remember", "https://github.com/city96/ComfyUI-GGUF"]
    # files are there, ComfyUI still has to load them
    assert client.get(f"/api/workflows/{wf['id']}/nodes-check").json()["packs"][0]["status"] == "restart"
    # after ComfyUI restarted and knows the node, the run goes ahead
    monkeypatch.setattr(nodepacks, "known_types", lambda refresh=True: {"SaveImage", "UnetLoaderGGUF"})
    assert client.get(f"/api/workflows/{wf['id']}/nodes-check").json()["packs"] == []


def test_no_check_without_comfyui_catalog(client, monkeypatch):
    monkeypatch.setattr(nodepacks, "known_types", lambda refresh=True: None)
    res = nodepacks.check_prompt({"1": {"class_type": "Anything", "inputs": {}}})
    assert res == {"available": False, "packs": [], "message": "Start ComfyUI to check which custom nodes are installed."}


def test_comfyui_errors_name_the_missing_nodes():
    from app.services.runs import _missing_node_types

    assert _missing_node_types("Node 'workflow/FLUX' not found. The custom node may not be installed.: Node ID '#28'") == ["workflow/FLUX"]
    assert _missing_node_types("Cannot execute because node UnetLoaderGGUF does not exist.") == ["UnetLoaderGGUF"]
    assert _missing_node_types("KSampler (ID 3) failed: out of memory") == []


def test_group_node_workflow_imports_and_old_imports_are_reconverted(client, tmp_path):
    from tests.lib.test_subgraphs import _group_workflow
    from app.services import workflows

    p = tmp_path / "flux_group.json"
    p.write_text(json.dumps(_group_workflow()), encoding="utf-8")
    with open(p, "rb") as f:
        wf = client.post("/api/workflows/upload", files={"file": ("flux_group.json", f, "application/json")}).json()
    ids = {n["id"] for n in client.get(f"/api/workflows/{wf['id']}/graph").json()["nodes"]}
    assert {"28:0", "28:1", "28:2", "7", "8", "26"} <= ids and "28" not in ids
    # simulate an import made by v1.0.7 (group node left in the prompt), then the start-up migration
    folder = workflows._root() / wf["id"]
    old = {"28": {"class_type": "workflow/FLUX", "inputs": {}}, "26": {"class_type": "PreviewImage", "inputs": {}}}
    (folder / "prompt.json").write_text(json.dumps(old), encoding="utf-8")
    (folder / "workflow.py").write_text("# old\\n", encoding="utf-8")
    assert workflows.needs_expansion(old)
    assert wf["id"] in workflows.migrate_group_nodes()
    assert "CheckpointLoaderSimple(" in (folder / "workflow.py").read_text(encoding="utf-8")
    assert any(h.name.endswith("_before_reconvert.py") for h in (folder / "history").iterdir())
