"""元数据缓存：读写回环、身份校验与文件权限。"""

import tempfile
import unittest
from pathlib import Path

from app.services.metadata_cache import read_metadata, write_metadata

METADATA = {"package": "example", "version": "1.0+42", "architecture": "amd64"}


class MetadataCacheTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache_dir = Path(directory.name)

    def test_roundtrip_and_identity_check(self):
        key = "a" * 64
        write_metadata(self.cache_dir, key, METADATA)
        self.assertEqual(read_metadata(self.cache_dir, key), METADATA)
        # 身份不符或字段缺失时按缓存损坏处理。
        self.assertIsNone(read_metadata(self.cache_dir, "b" * 64))

    def test_written_files_are_world_readable(self):
        """root 服务与普通用户 CLI 混用同一缓存时，双方都必须能读到对方的条目。"""
        key = "c" * 64
        write_metadata(self.cache_dir, key, METADATA)
        mode = (self.cache_dir / "metadata" / f"{key}.json").stat().st_mode & 0o777
        self.assertEqual(mode, 0o644)


if __name__ == "__main__":
    unittest.main()
