from collections import deque
from enum import Enum
import os
import time
import signal
import traceback
from typing import BinaryIO
import numpy as np
import json
from datetime import datetime, timedelta
import pytz
import argparse
import textwrap
from pprint import pprint


class CopyMode(Enum):
    NEW_FILES_ONLY = 1
    ALL_FILES = 2


class FileStatus(Enum):
    NEW = 1
    CACHED = 2
    PARTLY = 3
    DONE = 4


class DirectoryCache:
    def __init__(self, file_name: str = ".cache") -> None:
        self._file_name = file_name
        self._cache: dict = self.deserialize_from_file()
        self._max_age_in_weeks = 4

    # Serialize dictionary to a file
    def serialize_to_file(self):
        # Convert datetime to UNIX timestamp (milliseconds as uint64)
        _cutoff = datetime.now(tz=pytz.UTC) - timedelta(weeks=self._max_age_in_weeks)
        _data_serialized = {
            key: value
            for key, value in self._cache.items()
            if value > _cutoff.timestamp()
        }
        with open(self._file_name, "w") as file:
            json.dump(_data_serialized, file, indent=4)

    # Deserialize dictionary from a file
    def deserialize_from_file(self):
        try:
            if os.path.exists(self._file_name):
                with open(self._file_name, "r") as file:
                    return json.load(file)
        except:
            pass

        return {}

    def is_done(
        self, *, source_file, destination_file: str, copy_mode: CopyMode
    ) -> FileStatus:
        _ts_cache = self._cache.get(destination_file, 0.0)

        if copy_mode == CopyMode.NEW_FILES_ONLY:
            if _ts_cache == os.path.getmtime(source_file):
                return FileStatus.CACHED
            else:
                return FileStatus.NEW
        elif copy_mode == CopyMode.ALL_FILES:
            if os.path.isfile(destination_file):
                if _ts_cache == os.path.getmtime(destination_file):
                    return FileStatus.DONE
                else:
                    return FileStatus.PARTLY
            else:
                return FileStatus.NEW

        if os.path.isfile(destination_file):
            if _ts_cache == os.path.getmtime(source_file):
                return True

        return False
        # return os.path.isfile(destination_file) and self._cache.get(
        #     destination_file, 0.0
        # ) == os.path.getmtime(destination_file)

    def set_done(self, *, source_file: str, destination_file: str) -> None:
        _ts = os.path.getmtime(source_file)
        os.utime(destination_file, (_ts, _ts))
        self._cache[destination_file] = _ts
        self.serialize_to_file()


class RollingMedian:
    def __init__(self, window_size=10) -> None:
        self.window_size = window_size
        self.window = deque()

    def add(self, value):
        self.window.append(value)

        # Remove the oldest value if the window exceeds the specified size
        if len(self.window) > self.window_size:
            self.window.popleft()

    def median(self):
        # Return the median of the current window
        if not self.window:
            return 0
        return np.median(self.window)


class Copier:
    def __init__(self, block_size=2048, dry_run: bool = False) -> None:
        self.__abort = False
        self.__dry_run = dry_run
        self.__block_size = block_size
        self.__transfer_rate_median = RollingMedian()
        _path = os.path.dirname(__file__)
        self.__directory_cache = DirectoryCache(os.path.join(_path, ".cache"))

        def signal_handler(sig, frame):
            self.__abort = True
            print("\nCopying interrupted by user.")

        signal.signal(signal.SIGINT, signal_handler)

        if dry_run:
            print("\nDry run.")

    def copy(self, *, src: str, dst: str) -> None:
        if os.path.isfile(src):
            _dest = (
                os.path.join(dst, os.path.basename(src)) if os.path.isdir(dst) else dst
            )
            self.copy_file(src=src, dst=_dest)
        elif os.path.isfile(dst):
            print(
                f"Error: destination has to be a directory name since source is a directory"
            )
        else:
            self.__copy_directory(src=src, dest=dst)

    def _find_resume_position(
        self, *, source_file: str, destination_file: str, total_size: int
    ) -> int:
        """
        Finds the position in the destination file where the content starts to be different (mostly zero bytes) compared to the source file.
        :param source_file: File handle to the source file.
        :param destination_file: File handle to the destination file.
        :return: Position (offset) to resume writing.
        """

        _block_size = min(total_size, self.__block_size)

        def is_block_different(f_src: BinaryIO, f_dst: BinaryIO, offset: int) -> bool:
            f_src.seek(offset)
            f_dst.seek(offset)

            block_src = f_src.read(_block_size)
            block_dst = f_dst.read(_block_size)
            return block_src != block_dst

        def is_file_equal(f_src: BinaryIO, f_dst: BinaryIO, file_size: int) -> bool:
            _mismatch_start = is_block_different(f_src, f_dst, file_size - _block_size)
            _mismatch_end = is_block_different(f_src, f_dst, 0)
            return _mismatch_start or _mismatch_start

        start = 0
        end = total_size

        with open(destination_file, "rb") as f_dst:
            with open(source_file, "rb") as f_src:
                if not is_file_equal(f_src, f_dst, total_size):
                    while start + 1 < end:
                        mid = (start + end) // 2
                        if is_block_different(f_src, f_dst, mid):
                            end = mid
                        else:
                            start = mid
                else:
                    start = -1

        return start

    def __copy_directory(self, *, src: str, dest: str):
        self.__copy_directory_internal(src, dest, CopyMode.NEW_FILES_ONLY)
        self.__copy_directory_internal(src, dest, CopyMode.ALL_FILES)

    def __copy_directory_internal(self, src: str, dest: str, copy_mode: CopyMode):
        try:
            for _root, _, _files in os.walk(src):
                _rel_path_src = os.path.relpath(_root, start=src)

                for _file in _files:
                    if self.__abort:
                        return

                    _file_path_src = os.path.normpath(os.path.join(_root, _file))
                    _file_path_dest = os.path.normpath(
                        os.path.join(dest, _rel_path_src, _file)
                    )

                    _src_file_rel = os.path.normpath(os.path.join(_rel_path_src, _file))
                    _file_status = self.__directory_cache.is_done(
                        source_file=_file_path_src,
                        destination_file=_file_path_dest,
                        copy_mode=copy_mode,
                    )

                    if _file_status == FileStatus.CACHED:
                        print(f"File cached: {_src_file_rel}")
                        continue

                    elif _file_status == FileStatus.NEW:
                        # print(f"Copy new file: {_src_file_rel}")
                        self.copy_file(src=_file_path_src, dst=_file_path_dest)
                    elif _file_status == FileStatus.PARTLY:
                        # print(f"Check existing file: {_src_file_rel}")
                        self.copy_file(src=_file_path_src, dst=_file_path_dest)
                    elif _file_status == FileStatus.DONE:
                        print(f"File done: {_src_file_rel}")
                    else:
                        print(f"File status {_file_status} not implemented yet")

        except Exception as e:
            print(f"An error has occurred: {e}")
            traceback.print_exc()

    def copy_file(self, *, src: str, dst: str):
        """
        Copies a file to the destination, resuming from where the copy was interrupted if possible.
        :param source_file: Path to the source file.
        :param destination_file: Path to the destination file.
        """
        total_size = os.path.getsize(src)

        # Determine the resume position
        if os.path.exists(dst):
            print(f"Files exists remotely, find resume position {dst}")
            resume_position = self._find_resume_position(
                source_file=src, destination_file=dst, total_size=total_size
            )
        else:
            print(f"Files does not exist remotely {dst}")
            resume_position = 0

        if resume_position < 0:
            self.__directory_cache.set_done(source_file=src, destination_file=dst)
            print("Files are equal")
            return
        if resume_position == 0:
            pass
            # print(f"File is new: {os.path.basename(dst)}")
        else:
            _percentage = int((resume_position * 100) // total_size)
            print(f"File is incomplete ({_percentage:02d}%): {os.path.basename(dst)}")

        if self.__dry_run:
            return

        # Ensure the destination directory exists
        destination_dir = os.path.dirname(dst)
        if not os.path.exists(destination_dir):
            os.makedirs(destination_dir)

        print(
            f"File {os.path.basename(src)} mismatch. Start copying from {resume_position=} {total_size=}"
        )
        # return

        with open(src, "rb") as f_src, open(
            dst, "r+b" if resume_position > 0 else "wb"
        ) as f_dst:
            # Skip to the resume position in both files
            if resume_position > 0:
                f_src.seek(resume_position)
                f_dst.seek(resume_position)

            # Copy the remainder of the file with progress
            copied_size = resume_position
            last_shown_progress = None
            start_time = time.time()
            copied_size_since_last_progress_shown = 0

            while not self.__abort:
                chunk = f_src.read(5 * 1024 * 1024)  # Read in 5 MB chunks
                if not chunk:
                    break
                f_dst.write(chunk)
                _length_chunk = len(chunk)
                copied_size += _length_chunk
                progress = (copied_size * 100) // total_size
                copied_size_since_last_progress_shown += _length_chunk

                if progress != last_shown_progress and not self.__abort:
                    elapsed_time = time.time() - start_time
                    transfer_rate = (
                        (copied_size_since_last_progress_shown / (1024 * 1024))
                        / elapsed_time
                        if elapsed_time > 0
                        else 0
                    )
                    self.__transfer_rate_median.add(transfer_rate)
                    transfer_rate = self.__transfer_rate_median.median()

                    remaining_time = (
                        (total_size - copied_size) / (transfer_rate * 1024 * 1024)
                        if transfer_rate > 0
                        else float("inf")
                    )

                    remaining_minutes, remaining_seconds = divmod(remaining_time, 60)

                    last_shown_progress = progress
                    start_time = time.time()
                    copied_size_since_last_progress_shown = 0

                    print(
                        f"Progress: {progress:3d}% | Transfer rate: {transfer_rate:5.2f} MB/s | Remaining time: {int(remaining_minutes):02d}:{int(remaining_seconds):02d}"
                    )

        if not self.__abort:
            self.__directory_cache.set_done(source_file=src, destination_file=dst)
            print(f"File copied successfully: {os.path.basename(src)}.")


# if __name__ == "__main__":

#     source_path = input("Enter the source file path: ").strip()
#     destination_path = input(
#         "Enter the destination file path (including network share path): "
#     ).strip()

#     if not os.path.exists(source_path):
#         print("Source file does not exist.")
#     else:
#         try:
#             c = Copier(False)
#             c.copy_file_with_resume(source_path, destination_path)
#         except Exception as e:
#             print(f"An error occurred: {e}")


def parse_commandline() -> None:
    global _args

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""resumable file copier"""),
    )

    # add expected arguments
    parser.add_argument(
        "--src", dest="src", required=True, help="source file or folder"
    )
    parser.add_argument(
        "--dst", dest="dst", required=True, help="destination file or folder"
    )
    parser.add_argument(
        "-d",
        "--dry",
        dest="dry",
        required=False,
        help="do dry run",
        action="store_true",
    )

    return parser.parse_args()


if __name__ == "__main__":
    _args = parse_commandline()

    # pprint(_args)

    Copier(dry_run=_args.dry).copy(src=_args.src, dst=_args.dst)

    # c.copy_directory(
    #     r"d:\projects\IAV\tuner_middleware\RF-CATCHER\recordings\DAB-DAB_S-ANHALT_to_SACHSEN_MDR",
    #     r"o:\TMOI_DataStorage\Tuner-Recordings\RF-Catcher\DAB-DAB_S-ANHALT_to_SACHSEN_MDR",
    # )

    # c.copy_file(
    #     r"d:\projects\IAV\tuner_middleware\RF-CATCHER\recordings\DAB-DAB_S-ANHALT_to_SACHSEN_MDR\DAB-DAB_S-ANHALT_to_SACHSEN_MDR.7z.127",
    #     r"o:\TMOI_DataStorage\Tuner-Recordings\RF-Catcher\DAB-DAB_S-ANHALT_to_SACHSEN_MDR\DAB-DAB_S-ANHALT_to_SACHSEN_MDR.7z.127",
    # )
