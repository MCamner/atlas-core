from __future__ import annotations

from io import BytesIO
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.reproducible_build import (
    ReleaseIntegrityError,
    _normalize_sdist,
    read_sdist_metadata,
)


METADATA = b"Metadata-Version: 2.1\nName: atlas-core\nVersion: 1.0.0\n\n"


class TestSdistMetadata(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_sdist(
        self,
        members: list[tuple[str, bytes]],
        *,
        filename: str = "fixture.tar.gz",
        mtime: int = 0,
    ) -> Path:
        path = self.root / filename
        with tarfile.open(path, "w:gz") as archive:
            for name, content in members:
                member = tarfile.TarInfo(name)
                member.size = len(content)
                member.mtime = mtime
                archive.addfile(member, BytesIO(content))
        return path

    def test_reads_only_root_level_pkg_info(self) -> None:
        path = self.make_sdist(
            [
                ("atlas_core-1.0.0/PKG-INFO", METADATA),
                (
                    "atlas_core-1.0.0/atlas_core.egg-info/PKG-INFO",
                    b"Metadata-Version: 2.1\nName: wrong-package\nVersion: 9.9\n\n",
                ),
            ]
        )

        self.assertEqual(
            read_sdist_metadata(path),
            {"Name": "atlas-core", "Version": "1.0.0"},
        )

    def test_refuses_egg_info_pkg_info_without_root_metadata(self) -> None:
        path = self.make_sdist(
            [("atlas_core-1.0.0/atlas_core.egg-info/PKG-INFO", METADATA)]
        )

        with self.assertRaisesRegex(ReleaseIntegrityError, "root-level"):
            read_sdist_metadata(path)

    def test_refuses_multiple_tar_roots(self) -> None:
        path = self.make_sdist(
            [
                ("atlas_core-1.0.0/PKG-INFO", METADATA),
                ("another-root/file.txt", b"not package metadata\n"),
            ]
        )

        with self.assertRaisesRegex(ReleaseIntegrityError, "exactly one root"):
            read_sdist_metadata(path)

    def test_refuses_path_traversal(self) -> None:
        path = self.make_sdist(
            [
                ("atlas_core-1.0.0/PKG-INFO", METADATA),
                ("atlas_core-1.0.0/../escape.txt", b"outside root\n"),
            ]
        )

        with self.assertRaisesRegex(ReleaseIntegrityError, "unsafe path"):
            read_sdist_metadata(path)

    def test_normalizes_archive_timestamps_without_changing_metadata(self) -> None:
        members = [("atlas_core-1.0.0/PKG-INFO", METADATA)]
        build_a = self.make_sdist(members, filename="build-a.tar.gz", mtime=100)
        build_b = self.make_sdist(members, filename="build-b.tar.gz", mtime=200)

        _normalize_sdist(build_a, source_date_epoch=1234567890)
        _normalize_sdist(build_b, source_date_epoch=1234567890)

        self.assertEqual(build_a.read_bytes(), build_b.read_bytes())
        self.assertEqual(
            read_sdist_metadata(build_a),
            {"Name": "atlas-core", "Version": "1.0.0"},
        )

    def test_normalization_does_not_hide_member_content_mismatch(self) -> None:
        build_a = self.make_sdist(
            [("atlas_core-1.0.0/PKG-INFO", METADATA)],
            filename="build-a.tar.gz",
            mtime=100,
        )
        changed_metadata = b"Metadata-Version: 2.1\nName: atlas-core\nVersion: 2.0.0\n\n"
        build_b = self.make_sdist(
            [("atlas_core-1.0.0/PKG-INFO", changed_metadata)],
            filename="build-b.tar.gz",
            mtime=200,
        )

        _normalize_sdist(build_a, source_date_epoch=1234567890)
        _normalize_sdist(build_b, source_date_epoch=1234567890)

        self.assertNotEqual(build_a.read_bytes(), build_b.read_bytes())


if __name__ == "__main__":
    unittest.main()