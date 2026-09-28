"""Missing module -> the package that really provides it (never a blind same-name install)."""
import io
import json
import zipfile
from pathlib import Path

import pytest

from app.services import engines, pydeps

REAL_WRONG_NUNCHAKU = (Path(__file__).parent.parent / "data" / "pypi-nunchaku-0.16.1-py3-none-any.whl").read_bytes()
NUNCHAKU_IMPORTS = [{"module": "nunchaku", "names": ["NunchakuFluxTransformer2dModel"]},
                    {"module": "nunchaku.lora.flux", "names": ["to_diffusers"]}]


def _wheel(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


@pytest.fixture
def fake_pypi(files_dir, files_url, monkeypatch, tmp_path):
    monkeypatch.setattr(pydeps, "PYPI", files_url)
    cache = pydeps._cache_path()
    if cache.exists():
        cache.unlink()
    user = pydeps._user_path()
    if user.exists():
        user.unlink()

    def publish(package, wheel_bytes, filename):
        (files_dir / "whl").mkdir(exist_ok=True)
        (files_dir / "whl" / filename).write_bytes(wheel_bytes)
        d = files_dir / "pypi" / package
        d.mkdir(parents=True, exist_ok=True)
        (d / "json").write_text(json.dumps({"urls": [{"packagetype": "bdist_wheel", "filename": filename,
                                                        "size": len(wheel_bytes), "url": f"{files_url}/whl/{filename}"}]}))
    return publish


def test_the_unrelated_same_named_package_is_rejected(client, fake_pypi, monkeypatch):
    fake_pypi("nunchaku", REAL_WRONG_NUNCHAKU, "nunchaku-0.16.1-py3-none-any.whl")  # the real PyPI wheel
    monkeypatch.setattr(engines, "for_module", lambda m: None)  # even without the engine entry
    res = pydeps.resolve_module("nunchaku", None, NUNCHAKU_IMPORTS)
    assert res["package"] is None and "different library" in res["reason"]


def test_the_packs_own_requirements_decide_first(client, fake_pypi, tmp_path):
    fake_pypi("opencv-python-headless", _wheel({"cv2/__init__.py": "def imread(): pass\n"}), "opencv_python_headless-4.10-cp37-abi3-win_amd64.whl")
    pack = tmp_path / "ComfyUI-Thing"
    pack.mkdir()
    (pack / "requirements.txt").write_text("numpy\nopencv-python-headless>=4.8  # images\n")
    res = pydeps.resolve_module("cv2", pack, [{"module": "cv2", "names": ["imread"]}])
    assert (res["package"], res["source"]) == ("opencv-python-headless>=4.8", "pack requirements")
    # without the pack: the known-names list
    assert pydeps.resolve_module("cv2")["package"] == "opencv-python"


def test_same_name_only_after_checking_the_wheel(client, fake_pypi):
    fake_pypi("einops", _wheel({"einops/__init__.py": "def rearrange(): pass\n", "einops-0.8.dist-info/top_level.txt": "einops\n"}),
              "einops-0.8.0-py3-none-any.whl")
    res = pydeps.resolve_module("einops", None, [{"module": "einops", "names": ["rearrange"]}])
    assert (res["package"], res["source"]) == ("einops", "PyPI (checked)")
    assert "No PyPI package" in pydeps.resolve_module("zz_not_there")["reason"]


def test_the_users_answer_is_remembered(client, fake_pypi):
    pydeps.save_user_package("zz_not_there", "my-private-pkg==1.0")
    assert pydeps.resolve_module("zz_not_there") == {"module": "zz_not_there", "package": "my-private-pkg==1.0", "source": "you", "verified": True}
    assert client.post("/api/nodepacks/module-package", json={"module": "x", "package": "a; rm -rf /"}).status_code == 400


def test_engines_are_never_resolved_to_pypi(client, fake_pypi):
    fake_pypi("nunchaku", REAL_WRONG_NUNCHAKU, "nunchaku-0.16.1-py3-none-any.whl")
    res = pydeps.resolve_module("nunchaku", None, NUNCHAKU_IMPORTS)
    assert res["source"] == "engine" and res["engine"]["resolver"] == "versions_list"


def test_equivalent_package_from_the_pack_wins_without_pypi(client, tmp_path):
    pack = tmp_path / "ComfyUI-Thing2"
    pack.mkdir()
    (pack / "requirements.txt").write_text("opencv-python-headless>=4.8\n")
    res = pydeps.resolve_module("cv2", pack, check_pypi=False)  # Settings page: no downloads
    assert (res["package"], res["source"]) == ("opencv-python-headless>=4.8", "pack requirements")
    pending = pydeps.resolve_module("zz_private_sdk", pack, check_pypi=False)
    assert pending["pending"] and pending["package"] is None
