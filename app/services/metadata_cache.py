"""与 deb 文件生命周期独立的候选元数据缓存。仅使用标准库。"""

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path


def asset_key(repo: str, asset_id: int, size: int, updated_at: str, url: str) -> str:
    identity = [repo, asset_id, size, updated_at, url]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def read_metadata(cache_dir: Path, key: str):
    try:
        record = json.loads((cache_dir / "metadata" / f"{key}.json").read_text())
        if record.get("schema") != 1 or record.get("identity") != key:
            return None
        metadata = record["metadata"]
        if not all(
            isinstance(metadata.get(k), str) and metadata[k]
            for k in ("package", "version", "architecture")
        ):
            return None
        return metadata
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return None


def write_metadata(cache_dir: Path, key: str, metadata: dict) -> None:
    temporary = None
    try:
        directory = cache_dir / "metadata"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=directory, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump({"schema": 1, "identity": key, "metadata": metadata}, stream)
        os.replace(temporary, directory / f"{key}.json")
    except OSError as error:
        logging.getLogger(__name__).warning("无法保存候选版本缓存：%s", error)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    # CLI 与 Web 共用缓存格式；缓存中不保存可执行命令或安装路径。
    import sys

    action, *args = sys.argv[1:]
    if action == "key":
        repo, asset_id, size, updated, url = args
        print(asset_key(repo, int(asset_id), int(size), updated, url))
    elif action == "read":
        directory, key, package, architecture = args
        metadata = read_metadata(Path(directory), key)
        if (
            not metadata
            or metadata["package"] != package
            or metadata["architecture"] not in (architecture, "all")
        ):
            sys.exit(1)
        print(metadata["version"])
    elif action == "write":
        directory, key, package, architecture, version = args
        write_metadata(
            Path(directory),
            key,
            {
                "package": package,
                "architecture": architecture,
                "version": version,
            },
        )
