"""Explicit model provisioning. Only prepare_laya performs network I/O."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile


LAYA_VERSION = "0.3.5"
LAYA_REPO = "convaiinnovations/laya"
CHECKPOINTS = {"english": "", "multilingual": "multilingual", "typed-decisions": "typed-decisions"}
MANIFEST = "nova-model.json"
REQUIRED = {"rl_agent_config.json", "model.safetensors", "encoder/config.json",
            "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json"}


class ModelError(ValueError):
    """A safe diagnostic code; never contains model input or upstream exceptions."""


def read_json(path):
    if path.stat().st_size > 1048576:
        raise ModelError("invalid_model_config")
    def reject(value):
        raise ValueError("Nonfinite JSON")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_tokenizer(root):
    """Apply the pinned SDK's two compatibility repairs during setup, not scanning."""
    path = root / "tokenizer/tokenizer_config.json"
    config = read_json(path)
    if config.get("tokenizer_class") in (None, "TokenizersBackend"):
        config["tokenizer_class"] = "PreTrainedTokenizerFast"
        config.pop("backend", None)
        config.pop("is_local", None)
    extra = config.get("extra_special_tokens")
    if isinstance(extra, list):
        config["extra_special_tokens"] = {f"extra_{i}": value for i, value in enumerate(extra)}
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _check_layout(root):
    if any(not (root / name).is_file() for name in REQUIRED):
        raise ModelError("model_assets_missing")
    cfg = read_json(root / "rl_agent_config.json")
    if not isinstance(cfg, dict) or not {"encoder", "head_layers"} <= cfg.keys():
        raise ModelError("invalid_model_config")
    for field, default in (("max_len", 512), ("head_max_len", 192)):
        value = cfg.get(field, default)
        if type(value) is not int or not 1 <= value <= 8192:
            raise ModelError("invalid_model_config")
    for file in (root / "encoder").glob("*.json"):
        config = read_json(file)
        if not isinstance(config, dict) or config.get("auto_map"):
            raise ModelError("unsupported_model_config")
    tokenizer = read_json(root / "tokenizer/tokenizer_config.json")
    if not isinstance(tokenizer, dict) or tokenizer.get("auto_map"):
        raise ModelError("unsupported_model_config")
    if tokenizer.get("tokenizer_class") in (None, "TokenizersBackend") or isinstance(tokenizer.get("extra_special_tokens"), list):
        raise ModelError("model_not_prepared")


def validate_model(path):
    """Verify a complete prepared snapshot before handing its absolute path to Laya."""
    try:
        root = Path(path).expanduser().resolve()
        if not root.is_dir() or not (root / MANIFEST).is_file():
            raise ModelError("model_not_prepared")
        manifest = read_json(root / MANIFEST)
        if (not isinstance(manifest, dict) or manifest.get("format") != 1
                or manifest.get("laya_version") != LAYA_VERSION
                or manifest.get("repo") != LAYA_REPO
                or manifest.get("checkpoint") not in CHECKPOINTS
                or not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("revision", "")))):
            raise ModelError("invalid_model_manifest")
        hashes = manifest.get("sha256")
        if not isinstance(hashes, dict) or not REQUIRED <= hashes.keys():
            raise ModelError("invalid_model_manifest")
        actual = set()
        for file in root.rglob("*"):
            if file.is_symlink():
                raise ModelError("invalid_model_manifest")
            if file.is_file() and file.name != MANIFEST:
                actual.add(file.relative_to(root).as_posix())
        if actual != set(hashes):
            raise ModelError("model_assets_changed")
        for name, expected in hashes.items():
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or "\\" in name:
                raise ModelError("invalid_model_manifest")
            if not isinstance(expected, str) or checksum(root / name) != expected:
                raise ModelError("model_assets_changed")
        _check_layout(root)
        return root, manifest
    except ModelError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise ModelError("invalid_model_config") from None


def prepare_laya(checkpoint, output, revision="main"):
    """Download one immutable checkpoint into a new standalone directory."""
    if checkpoint not in CHECKPOINTS:
        raise ModelError("unknown_checkpoint")
    target = Path(output).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise ModelError("destination_exists")
    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError:
        raise ModelError("missing_laya_dependency") from None
    lock = target.with_name(f".{target.name}.prepare.lock")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ModelError("preparation_in_progress") from None
    except OSError:
        raise ModelError("destination_unavailable") from None
    os.close(fd)
    try:
        if target.exists() or target.is_symlink():
            raise ModelError("destination_exists")
        sha = HfApi().model_info(LAYA_REPO, revision=revision).sha
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ModelError("invalid_model_revision")
        prefix = CHECKPOINTS[checkpoint]
        prefix = prefix + "/" if prefix else ""
        snapshot = Path(snapshot_download(
            LAYA_REPO, revision=sha,
            allow_patterns=[prefix + name for name in
                            ("rl_agent_config.json", "model.safetensors", "tokenizer/*", "encoder/*")],
        )) / CHECKPOINTS[checkpoint]
        with tempfile.TemporaryDirectory(prefix=f".{target.name}-", dir=target.parent) as temporary:
            staging = Path(temporary) / "model"
            staging.mkdir()
            for name in ("rl_agent_config.json", "model.safetensors", "tokenizer", "encoder"):
                source, destination = snapshot / name, staging / name
                if source.is_dir():
                    shutil.copytree(source, destination)
                elif source.is_file():
                    shutil.copyfile(source, destination)
                else:
                    raise ModelError("model_assets_missing")
            _normalize_tokenizer(staging)
            _check_layout(staging)
            manifest = {"format": 1, "laya_version": LAYA_VERSION, "repo": LAYA_REPO,
                        "checkpoint": checkpoint, "revision": sha,
                        "sha256": {file.relative_to(staging).as_posix(): checksum(file)
                                   for file in sorted(staging.rglob("*")) if file.is_file()}}
            (staging / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            if target.exists() or target.is_symlink():
                raise ModelError("destination_exists")
            staging.rename(target)
        return target
    except ModelError:
        raise
    except Exception:
        raise ModelError("model_preparation_failed") from None
    finally:
        lock.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Explicit setup for NOVA System 1 models")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-laya", help="Download one pinned Laya snapshot; no inference")
    prepare.add_argument("--checkpoint", choices=tuple(CHECKPOINTS), default="english")
    prepare.add_argument("--output", required=True, help="New local directory; existing directories are never overwritten")
    prepare.add_argument("--revision", default="main", help="Hugging Face revision, resolved to a commit before downloading")
    args = parser.parse_args(argv)
    try:
        path = prepare_laya(args.checkpoint, args.output, args.revision)
    except ModelError as error:
        parser.exit(1, f"Model setup failed: {error}. Install NOVA's [laya] extra; use a new output directory.\n")
    print(f"Prepared Laya model: {path}")
    print(f"Use --sys1 --sys1-provider laya --sys1-model {path} --sys1-device cpu")


if __name__ == "__main__":
    main()
