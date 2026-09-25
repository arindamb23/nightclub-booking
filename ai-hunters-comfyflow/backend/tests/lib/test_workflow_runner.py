import json
import pytest
import websocket

from cb2c_py.lib.workflow import Workflow
from cb2c_py.lib.workflow_runner import WorkflowRunner, ComfyUIError, WorkflowCancelled, file_kind
from cb2c_py.nodes.generated.loadimage import LoadImage


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self.ok = status < 400
        self._payload = payload
        self.content = content
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


class FakeWS:
    def __init__(self, messages):
        self.messages = list(messages)
        self.closed = False

    def connect(self, *a, **k):
        pass

    def settimeout(self, t):
        pass

    def recv(self):
        if not self.messages:
            raise websocket.WebSocketConnectionClosedException()
        m = self.messages.pop(0)
        return m if isinstance(m, bytes) else json.dumps(m)

    def close(self):
        self.closed = True


@pytest.fixture
def runner():
    return WorkflowRunner("test.server:1234")


def test_file_kind():
    assert file_kind("a.PNG") == "image"
    assert file_kind("a.mp4") == "video"
    assert file_kind("a.webp") == "image"
    assert file_kind("a.txt") == "file"


def test_queue_prompt_formats_node_errors(runner, mocker):
    mocker.patch("requests.post", return_value=FakeResponse(400, {
        "error": {"message": "Prompt outputs failed validation", "details": ""},
        "node_errors": {"3": {"class_type": "KSampler", "errors": [
            {"details": "cfg 45 > max 30", "extra_info": {"input_name": "cfg"}}]}},
    }))
    with pytest.raises(ComfyUIError) as e:
        runner._queue_prompt({"prompt": {}}, "cid")
    assert "Prompt outputs failed validation" in str(e.value)
    assert e.value.details == ["Node KSampler (ID 3) input 'cfg': cfg 45 > max 30"]


def test_collect_output_refs_dedupes_and_reads_all_keys():
    history = {"outputs": {
        "9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]},
        "10": {"gifs": [{"filename": "v.mp4", "subfolder": "", "type": "output"}],
               "images": [{"filename": "a.png", "subfolder": "", "type": "output"}]},
    }}
    history["outputs"]["11"] = {"images": [{"filename": "anim.webp", "subfolder": "", "type": "output"}], "animated": [True]}
    refs = WorkflowRunner.collect_output_refs(history)
    assert [(r["filename"], r["kind"]) for r in refs] == [("a.png", "image"), ("v.mp4", "video"), ("anim.webp", "animation")]


def test_run_workflow_downloads_each_file_once(runner, mocker, tmp_path):
    ws = FakeWS([
        b"binary-preview",
        {"type": "executing", "data": {"node": "1", "prompt_id": "p1"}},
        {"type": "progress", "data": {"value": 1, "max": 2, "prompt_id": "p1"}},
        {"type": "executing", "data": {"node": None, "prompt_id": "p1"}},
    ])
    mocker.patch("websocket.WebSocket", return_value=ws)
    mocker.patch("requests.post", return_value=FakeResponse(200, {"prompt_id": "p1"}))
    history = {"p1": {"outputs": {
        "1": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]},
        "2": {"images": [{"filename": "out2.png", "subfolder": "", "type": "output"}]},
    }}}

    def fake_get(url, **kw):
        if "/history/" in url:
            return FakeResponse(200, history)
        return FakeResponse(200, content=b"PNG" + kw["params"]["filename"].encode())

    get = mocker.patch("requests.get", side_effect=fake_get)
    wf = Workflow()
    wf.add_node(LoadImage(image="x.png"))
    messages = []
    saved = runner.run_workflow(wf, messages.append, output_dir=str(tmp_path))
    assert [s["filename"] for s in saved] == ["out.png", "out2.png"]
    assert (tmp_path / "out.png").read_bytes() == b"PNGout.png"
    assert sum(1 for c in get.call_args_list if "/view" in c.args[0]) == 2
    assert len(messages) == 3
    assert ws.closed


def test_execution_error_raises_and_closes(runner, mocker, tmp_path):
    ws = FakeWS([{"type": "execution_error", "data": {"prompt_id": "p1", "node_id": "3", "node_type": "KSampler",
                                                      "exception_type": "RuntimeError", "exception_message": "OOM"}}])
    mocker.patch("websocket.WebSocket", return_value=ws)
    mocker.patch("requests.post", return_value=FakeResponse(200, {"prompt_id": "p1"}))
    with pytest.raises(ComfyUIError, match="KSampler .*OOM"):
        runner.run_workflow(Workflow(), output_dir=str(tmp_path))
    assert ws.closed


def test_cancel_interrupts(runner, mocker, tmp_path):
    import threading
    ev = threading.Event()
    ev.set()
    mocker.patch("websocket.WebSocket", return_value=FakeWS([]))
    post = mocker.patch("requests.post", return_value=FakeResponse(200, {"prompt_id": "p1"}))
    with pytest.raises(WorkflowCancelled):
        runner.run_workflow(Workflow(), output_dir=str(tmp_path), cancel_event=ev)
    assert any("/interrupt" in c.args[0] for c in post.call_args_list)


def test_upload_flag_uploads_local_image(runner, mocker, tmp_path):
    img = tmp_path / "in.png"
    img.write_bytes(b"x")
    wf = Workflow()
    node = wf.add_node(LoadImage(image=str(img)))
    node.upload = True
    mocker.patch.object(runner, "upload_file", return_value="in.png")
    mocker.patch("websocket.WebSocket", return_value=FakeWS([{"type": "execution_success", "data": {"prompt_id": "p1"}}]))
    post = mocker.patch("requests.post", return_value=FakeResponse(200, {"prompt_id": "p1"}))
    mocker.patch("requests.get", return_value=FakeResponse(200, {"p1": {"outputs": {}}}))
    runner.run_workflow(wf, output_dir=str(tmp_path))
    sent = post.call_args.kwargs["json"]["prompt"]
    assert sent[node.id]["inputs"]["image"] == "in.png"


def test_decode_binary_preview_frames():
    from cb2c_py.lib.workflow_runner import WorkflowRunner

    jpeg = (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + b"\xff\xd8data"
    assert WorkflowRunner._decode_preview(jpeg) == {"image": b"\xff\xd8data", "mime": "image/jpeg"}
    meta = b'{"image_type": "image/png", "node_id": "3"}'
    framed = (4).to_bytes(4, "big") + len(meta).to_bytes(4, "big") + meta + b"\x89PNG"
    assert WorkflowRunner._decode_preview(framed) == {"image": b"\x89PNG", "mime": "image/png"}
    assert WorkflowRunner._decode_preview(b"\x00\x00") is None
    assert WorkflowRunner._decode_preview((9).to_bytes(4, "big") * 3) is None
