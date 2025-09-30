from copier import *
import unittest
from unittest.mock import patch
from fs.memoryfs import MemoryFS
from parameterized import parameterized


class TestWithVirtualFileSystem(unittest.TestCase):
    def setUp(self):
        # Create a virtual file system
        self.vfs = MemoryFS()

        # Mock open() and os.path.exists() to use the virtual file system
        self.open_patcher = patch("builtins.open", new=self._mock_open())
        self.exists_patcher = patch("os.path.exists", new=self._mock_exists)
        self.mtime_patcher = patch("os.path.getmtime", new=self._mock_getmtime)
        self.utime_patcher = patch("os.utime", new=self._mock_utime)

        # Start the patchers
        self.open_patcher.start()
        self.exists_patcher.start()
        self.mtime_patcher.start()
        self.utime_patcher.start()

    def tearDown(self):
        # Stop the patchers
        self.open_patcher.stop()
        self.exists_patcher.stop()
        self.mtime_patcher.stop()
        self.utime_patcher.stop()

        # Close the virtual file system
        self.vfs.close()

    def _mock_open(self):
        """Return a mocked open() that uses the virtual file system."""

        def _open(file, mode="r", *args, **kwargs):
            # Map 'open' to the virtual file system
            if "b" in mode:
                return self.vfs.openbin(file, mode)
            else:
                return self.vfs.open(file, mode)

        return _open

    def _mock_exists(self, path) -> bool:
        """Return a mocked os.path.exists() that uses the virtual file system."""
        return self.vfs.exists(path)

    def _mock_getmtime(self, path) -> float:
        """Return a mocked os.path.getmtime() that uses the virtual file system."""
        if not self.vfs.exists(path):
            raise FileNotFoundError(f"No such file or directory: '{path}'")
        # Get the modified time from the virtual file system
        return self.vfs.getinfo(path, namespaces="details").modified.timestamp()

    def _mock_utime(self, path, times: tuple[int, int] | tuple[float, float] | None = None) -> float:
        """Return a mocked os.utime() that uses the virtual file system."""
        if not self.vfs.exists(path):
            raise FileNotFoundError(f"No such file or directory: '{path}'")

        # todo: maybe cache times in a dict ?

    @parameterized.expand(
        [
            ("0", 0, 10, 0),
            ("1", 1, 9, 0),
            ("2", 2, 8, 0),
            ("3", 3, 7, 1),
            ("4", 4, 6, 2),
            ("5", 5, 5, 3),
            ("6", 6, 6, 4),
            ("7", 7, 7, 5),
            ("8", 8, 8, 6),
            ("9", 9, 9, 7),
            ("10", 10, 0, -1),  # complete
        ]
    )
    def test_find_resume_position(self, _, bytes_good, bytes_bad, expected_result):
        with open("test_dst.bin", "wb") as f_dst:
            with open("test_src.bin", "wb") as f_src:
                for _ in range(0, bytes_good):
                    f_src.write(b"\x01")
                    f_dst.write(b"\x01")
                for _ in range(0, bytes_bad):
                    f_src.write(b"\x01")
                    f_dst.write(b"\x00")

        c = Copier(block_size=2)
        _pos = c._find_resume_position(source_file="test_src.bin", destination_file="test_dst.bin", total_size_src=10, total_size_dst=10)
        assert _pos == expected_result, f"Result: {_pos=}"

    def test_directory_cache(self):
        _c = DirectoryCache()
        with open("test", "w+") as f:
            pass

        assert _c.is_done(source_file="test", destination_file="test", copy_mode=CopyMode.NEW_FILES_ONLY) == FileStatus.NEW
        _c.set_done(source_file="test", destination_file="test")
        assert _c.is_done(source_file="test", destination_file="test", copy_mode=CopyMode.NEW_FILES_ONLY) == FileStatus.CACHED

        _c1 = DirectoryCache()
        assert _c1.is_done(source_file="test", destination_file="test", copy_mode=CopyMode.NEW_FILES_ONLY) == FileStatus.CACHED

    def test_RollingMedian(self):
        _m = RollingMedian(window_size=3)
        assert _m.median() == 0
        _m.add(10)
        assert _m.median() == 10
        _m.add(20)
        assert _m.median() == 15
        _m.add(30)
        assert _m.median() == 20
        _m.add(40)
        assert _m.median() == 30
