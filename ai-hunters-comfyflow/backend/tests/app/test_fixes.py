"""Known run errors: matched, explained, fixed with one click (pip into ComfyUI's Python + restart)."""
from app.services import fixes, nodepacks
from tests.app.conftest import wait_for

HY_ERROR = "DownloadAndLoadHyVideoTextEncoder (ID 16) failed: AttributeError 'CLIPTextModel' object has no attribute 'text_model'"


def test_known_errors_are_recognised():
    fix = fixes.match(HY_ERROR)
    assert fix["id"] == "transformers-clip-text-model"
    assert fix["actions"] == [{"type": "pip", "args": ["transformers>=4.49,<5.6"]}] and fix["restart"]
    mod = fixes.match("SomeNode (ID 3) failed: ModuleNotFoundError No module named 'cv2'")
    assert mod["title"].endswith("cv2") and mod["actions"][0]["args"] == ["opencv-python"]
    assert fixes.match("KSampler (ID 3) failed: out of memory") is None


def test_constraints_are_used_for_custom_node_installs():
    args = fixes.constraint_args()
    assert args[0] == "-c" and args[1].endswith("python-constraints.txt")
    assert "transformers>=4.49,<5.6" in open(args[1], encoding="utf-8").read()


def test_failed_run_offers_the_fix_and_applies_it(client, monkeypatch):
    from cb2c_py.lib.workflow_runner import ComfyUIError, WorkflowRunner
    from tests.app.test_api import _import_sample, _wait_run

    def crash(self, wf, *a, **kw):
        raise ComfyUIError(HY_ERROR)
    monkeypatch.setattr(WorkflowRunner, "run_workflow", crash)
    wf = _import_sample(client, "Fix Test")
    from app.services import workflows
    for row in workflows.detect_models(wf["id"]):  # pretend the model is there
        from pathlib import Path
        Path(row["path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(row["path"]).write_bytes(b"x")
    done = _wait_run(client, client.post("/api/runs", json={"workflow_id": wf["id"]}).json()["id"])
    assert done["status"] == "failed" and done["error_code"] == "known_fix"
    assert done["fix"]["id"] == "transformers-clip-text-model" and "5.6" in done["fix"]["explain"]

    commands = []
    monkeypatch.setattr(nodepacks, "_run", lambda job, args, cwd=None, timeout=1800, publish=None: commands.append(args))
    monkeypatch.setattr(nodepacks, "restart_comfyui", lambda wait=False: {"status": "done"})
    job = client.post(f"/api/runs/{done['id']}/fix").json()
    assert job["id"] == "transformers-clip-text-model"
    finished = wait_for(lambda: next((j for j in client.get("/api/fixes/jobs").json()["jobs"] if j["status"] in ("done", "error")), None))
    assert finished["status"] == "done", finished
    assert commands[0][1:4] == ["-m", "pip", "install"] and commands[0][-1] == "transformers>=4.49,<5.6"
    assert client.post("/api/runs/nope_1/fix").status_code == 404
