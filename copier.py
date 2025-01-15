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

    def is_done(self, destination_file: str) -> bool:
        return os.path.isfile(destination_file) and self._cache.get(
            destination_file, 0.0
        ) == os.path.getmtime(destination_file)

    def set_done(self, destination_file: str) -> None:
        self._cache[destination_file] = os.path.getmtime(destination_file)
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


class CopyMode(Enum):
    NEW_FILES_ONLY = 1
    ALL_FILES = 2


class Copier:
    def __init__(self, block_size=1024, dry_run: bool = False) -> None:
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

    def _find_resume_position(
        self, source_file: str, destination_file: str, total_size: int
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
            return not is_block_different(f_src, f_dst, file_size - _block_size)

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

    def copy_directory(self, src: str, dest: str):
        self.__copy_directory_internal(src, dest, CopyMode.NEW_FILES_ONLY)
        self.__copy_directory_internal(src, dest, CopyMode.ALL_FILES)

    def __copy_directory_internal(self, src: str, dest: str, copy_mode: CopyMode):
        try:
            for _root, _, _files in os.walk(src):
                _rel_path_src = os.path.relpath(_root, start=src)

                for _file in _files:
                    if self.__abort:
                        return

                    _file_path_src = os.path.join(_root, _file)
                    _file_path_dest = os.path.join(dest, _rel_path_src, _file)

                    if self.__directory_cache.is_done(_file_path_dest):
                        print(f"File cached: {os.path.join(_rel_path_src, _file)}")
                        continue

                    if copy_mode == CopyMode.NEW_FILES_ONLY and not os.path.isfile(
                        _file_path_dest
                    ):
                        print(f"Copy new file: {os.path.join(_rel_path_src, _file)}")
                        self.copy_file(_file_path_src, _file_path_dest)
                    elif copy_mode == CopyMode.ALL_FILES:
                        print(
                            f"Check existing file: {os.path.join(_rel_path_src, _file)}"
                        )
                        self.copy_file(_file_path_src, _file_path_dest)

        except Exception as e:
            print(f"An error has occurred: {e}")
            traceback.print_exc()

    def copy_file(self, source_file: str, destination_file: str):
        """
        Copies a file to the destination, resuming from where the copy was interrupted if possible.
        :param source_file: Path to the source file.
        :param destination_file: Path to the destination file.
        """
        total_size = os.path.getsize(source_file)

        # Determine the resume position
        if os.path.exists(destination_file):
            resume_position = self._find_resume_position(
                source_file, destination_file, total_size
            )
        else:
            resume_position = 0

        if resume_position < 0:
            self.__directory_cache.set_done(destination_file)
            print("Files are equal")
            return
        if resume_position == 0:
            print(f"File is new: {os.path.basename(destination_file)}")
        else:
            _percentage = int((resume_position * 100) // total_size)
            print(
                f"File is incomplete ({_percentage:02d}%): {os.path.basename(destination_file)}"
            )

        if self.__dry_run:
            return

        # Ensure the destination directory exists
        destination_dir = os.path.dirname(destination_file)
        if not os.path.exists(destination_dir):
            os.makedirs(destination_dir)

        print(
            f"File {os.path.basename(source_file)} mismatch. Start copying from {resume_position=} {total_size=}"
        )
        # return

        with open(source_file, "rb") as src, open(
            destination_file, "r+b" if resume_position > 0 else "wb"
        ) as dst:
            # Skip to the resume position in both files
            if resume_position > 0:
                src.seek(resume_position)
                dst.seek(resume_position)

            # Copy the remainder of the file with progress
            copied_size = resume_position
            last_shown_progress = None
            start_time = time.time()
            copied_size_since_last_progress_shown = 0

            while not self.__abort:
                chunk = src.read(1024 * 1024)  # Read in 1 MB chunks
                if not chunk:
                    break
                dst.write(chunk)
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
            self.__directory_cache.set_done(destination_file)
            print(f"File copied successfully: {os.path.basename(source_file)}.")


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
