"""Model preparation, integrity and offline runtime loading contracts."""

from importlib.metadata import PackageNotFoundError, requires
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nova.evaluators.sys1 import models
from nova.evaluators.sys1 import laya as adapter
from test_laya import Agent, evaluator, patterns


def write_snapshot(root, normalized=False):
    (root / "encoder").mkdir(parents=True)
    (root / "tokenizer").mkdir()
    (root / "rl_agent_config.json").write_text(json.dumps({"encoder": "upstream/encoder", "head_layers": 2}))
    (root / "model.safetensors").write_bytes(b"fixture-not-real-weights")
    (root / "encoder/config.json").write_text('{"model_type": "modernbert"}')
    (root / "tokenizer/tokenizer.json").write_text('{}')
    (root / "tokenizer/tokenizer_config.json").write_text(json.dumps({
        "tokenizer_class": "PreTrainedTokenizerFast" if normalized else "TokenizersBackend",
        "extra_special_tokens": {} if normalized else ["<test>"]}))
    return root


@pytest.fixture
def hub(monkeypatch, tmp_path):
    snapshot = tmp_path / "snapshot"
    write_snapshot(snapshot)
    for subfolder in ("multilingual", "typed-decisions"):
        write_snapshot(snapshot / subfolder)
    api = Mock()
    api.model_info.return_value.sha = "a" * 40
    download = Mock(return_value=str(snapshot))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=lambda: api, snapshot_download=download))
    return api, download


@pytest.mark.parametrize("checkpoint", models.CHECKPOINTS)
def test_prepare_selects_only_checkpoint_and_pins_revision(hub, tmp_path, checkpoint):
    api, download = hub
    target = models.prepare_laya(checkpoint, tmp_path / "prepared", "custom-tag")
    api.model_info.assert_called_once_with(models.LAYA_REPO, revision="custom-tag")
    kwargs = download.call_args.kwargs
    assert kwargs["revision"] == "a" * 40
    prefix = "" if checkpoint == "english" else checkpoint + "/"
    assert kwargs["allow_patterns"] == [prefix + p for p in ("rl_agent_config.json", "model.safetensors", "tokenizer/*", "encoder/*")]
    root, manifest = models.validate_model(target)
    assert root == target and manifest["checkpoint"] == checkpoint
    assert (root / "tokenizer/tokenizer_config.json").read_text().count("PreTrainedTokenizerFast") == 1
    assert not (root / "multilingual").exists()
    # Checksums describe the normalized local snapshot, never the mutable HF cache.
    assert manifest["sha256"]["tokenizer/tokenizer_config.json"] == models.checksum(root / "tokenizer/tokenizer_config.json")


def test_existing_destination_is_never_changed(hub, tmp_path):
    target = models.prepare_laya("english", tmp_path / "prepared")
    before = (target / models.MANIFEST).read_bytes()
    with pytest.raises(models.ModelError, match="destination_exists"):
        models.prepare_laya("english", target)
    assert (target / models.MANIFEST).read_bytes() == before
    assert hub[1].call_count == 1


def test_failed_preparation_leaves_no_destination_or_lock(hub, tmp_path):
    hub[1].side_effect = RuntimeError("private-token-marker")
    target = tmp_path / "prepared"
    with pytest.raises(models.ModelError, match="model_preparation_failed") as error:
        models.prepare_laya("english", target)
    assert "private-token-marker" not in str(error.value)
    assert not target.exists()
    assert not target.with_name(".prepared.prepare.lock").exists()


@pytest.mark.parametrize("change", ["missing", "tampered", "extra", "symlink", "manifest", "remote_code"])
def test_invalid_assets_rejected_without_network(hub, tmp_path, change):
    root = models.prepare_laya("english", tmp_path / "prepared")
    hub[1].reset_mock()
    if change == "missing":
        (root / "encoder/config.json").unlink()
    elif change == "tampered":
        (root / "model.safetensors").write_bytes(b"different")
    elif change == "extra":
        (root / "unexpected.txt").write_text("unexpected")
    elif change == "symlink":
        (root / "link").symlink_to(root / "model.safetensors")
    elif change == "manifest":
        (root / models.MANIFEST).write_text('{"format": 9}')
    else:
        (root / "encoder/config.json").write_text('{"auto_map": {"AutoModel": "custom.Class"}}')
        manifest = json.loads((root / models.MANIFEST).read_text())
        manifest["sha256"]["encoder/config.json"] = models.checksum(root / "encoder/config.json")
        (root / models.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(models.ModelError):
        models.validate_model(root)
    hub[1].assert_not_called()


def test_missing_dependency_and_sdk_version_are_diagnostics(monkeypatch):
    monkeypatch.setattr(adapter, "validate_model", lambda path: (Path(path), {}))
    for value, expected in [("0.3.4", "unsupported_laya_version"), (None, "missing_laya_dependency")]:
        def version(name):
            if value is None:
                raise PackageNotFoundError(name)
            return value
        monkeypatch.setattr(adapter, "version", version)
        e = evaluator()
        e._agent = None
        assert e.evaluate_many(patterns(), "sample").evaluations["$n"].reason == expected


def test_cuda_unavailable_is_not_a_cpu_fallback(monkeypatch):
    monkeypatch.setattr(adapter, "validate_model", lambda path: (Path(path), {}))
    monkeypatch.setattr(adapter, "version", lambda name: "0.3.5")
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(device=lambda value: SimpleNamespace(type="cuda", index=None),
                                                            cuda=SimpleNamespace(is_available=lambda: False)))
    load = Mock()
    monkeypatch.setitem(sys.modules, "laya", SimpleNamespace(load=load))
    e = evaluator(device="cuda")
    e._agent = None
    assert e.evaluate_many(patterns(), "sample").evaluations["$n"].reason == "device_unavailable"
    load.assert_not_called()


def test_model_load_uses_prepared_absolute_path_and_records_adjustments(hub, tmp_path, monkeypatch):
    root = models.prepare_laya("english", tmp_path / "prepared")
    monkeypatch.setattr(adapter, "version", lambda name: "0.3.5")
    class Device:
        type = "cpu"
        def __str__(self):
            return "cpu"
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(device=lambda value: Device()))
    agent = Agent()
    agent.temperature = [1, 1, 1]
    agent.temperature_raw = [1, 1, 1]
    agent.temperature_by_options = {"choice:11+": .5}
    agent.temperature_by_options_raw = {"choice:11+": .1}
    load = Mock(return_value=agent)
    monkeypatch.setitem(sys.modules, "laya", SimpleNamespace(load=load))
    e = adapter.LayaSys1Evaluator({"provider": "laya", "enabled": True, "model": str(root)})
    batch = e.evaluate_many(patterns(), "sample")
    assert all(item.status == "evaluated" for item in batch.evaluations.values())
    load.assert_called_once_with(str(root.resolve()), device="cpu")
    assert batch.metadata["warnings"] == ["checkpoint_temperatures_adjusted_by_laya"]
    e.evaluate_many(patterns(), "sample")
    assert load.call_count == 1


def test_extra_is_isolated_and_entry_point_help():
    dependencies = requires("nova-hunting")
    assert any('laya==0.3.5' in d and 'extra == "laya"' in d for d in dependencies)
    assert not any(d.startswith("laya") and 'extra == "laya"' not in d for d in dependencies)
