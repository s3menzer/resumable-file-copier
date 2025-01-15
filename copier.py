from collections import deque
import os
import time
import signal
import numpy as np


class RollingMedian:
    def __init__(self, number_of_samples=10) -> None:
        self.number_of_samples = number_of_samples
        self.window = deque()

    def add(self, value):
        self.window.append(value)

        # Remove the oldest value if the window exceeds the specified size
        if len(self.window) > self.window_size:
            self.window.popleft()

    def median(self):
        # Return the median of the current window
        if not self.window:
            return None  # Handle the case where the window is empty
        return np.median(self.window)


class Copier:
    def __init__(self, check_all_files=False) -> None:
        self.abort = False
        self.check_all_files = check_all_files
        self.block_size = 1024

    def find_resume_position(self, source_file, destination_file):
        """
        Finds the position in the destination file where the content starts being zeroed out using binary search.
        :param destination_file: Path to the destination file.
        :return: Position (offset) to resume writing.
        """

        def is_block_different(f_src, f_dst, offset):
            f_src.seek(offset)
            f_dst.seek(offset)

            block_src = f_src.read(self.block_size)
            block_dst = f_dst.read(self.block_size)
            _res = block_src != block_dst
            # print(f"{_res=} {block=}")
            return _res

        def is_file_equal(f_src, f_dst, file_size):
            return not is_block_different(f_src, f_dst, file_size - self.block_size)

        file_size = os.path.getsize(destination_file)
        start, end = 0, file_size

        """
        11111 11000
        xxxxx 11 000
        xxxxx xx 000
                  
        """
        with open(destination_file, "rb") as f_dst:
            with open(source_file, "rb") as f_src:
                if not is_file_equal(f_src, f_dst, file_size):
                    while start + 1 < end:
                        mid = (start + end) // 2
                        # print(f"Test {mid}, range={[start, end]}")
                        if is_block_different(f_src, f_dst, mid):
                            end = mid
                            # print(f"-> Search in the first half")
                        else:
                            start = mid
                            # print(f"-> Search in the second half")

                else:
                    start = -1

        return start

    def copy_directory(self, src, dest, start_file_name):
        try:
            start_file_found = False
            for root, _, files in os.walk(src):
                rel_path_src = os.path.relpath(root, start=src)

                for file in files:
                    if self.abort:
                        return
                    if not start_file_found and file != start_file_name:
                        continue

                    start_file_found = True

                    file_path_src = os.path.join(root, file)
                    file_path_dest = os.path.join(dest, rel_path_src, file)
                    if not os.path.isfile(file_path_dest) or self.check_all_files:
                        print(f"Process {os.path.join(rel_path_src, file)}")
                        self.copy_file_with_resume(file_path_src, file_path_dest)

        except Exception as e:
            print(f"Ein Fehler ist aufgetreten: {e}")

    def copy_file_with_resume(self, source_file, destination_file):
        """
        Copies a file to the destination, resuming from where the copy was interrupted if possible.
        :param source_file: Path to the source file.
        :param destination_file: Path to the destination file.



        todo: quick check last block_size bytes which indicates files are equal
        """
        self.abort = False

        def signal_handler(sig, frame):
            print("\nCopying interrupted by user.")
            self.abort = True

        signal.signal(signal.SIGINT, signal_handler)

        # Ensure the destination directory exists
        destination_dir = os.path.dirname(destination_file)
        if not os.path.exists(destination_dir):
            os.makedirs(destination_dir)

        # Determine the resume position
        if os.path.exists(destination_file):
            resume_position = self.find_resume_position(source_file, destination_file)
        else:
            resume_position = 0

        total_size = os.path.getsize(source_file)

        if resume_position < 0:
            print("Files are equal")
            return

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

            while not self.abort:
                chunk = src.read(1024 * 1024)  # Read in 1 MB chunks
                if not chunk:
                    break
                dst.write(chunk)
                _length_chunk = len(chunk)
                copied_size += _length_chunk
                progress = (copied_size * 100) // total_size
                copied_size_since_last_progress_shown += _length_chunk

                if progress != last_shown_progress and not self.abort:
                    elapsed_time = time.time() - start_time
                    transfer_rate = (
                        (copied_size_since_last_progress_shown / (1024 * 1024))
                        / elapsed_time
                        if elapsed_time > 0
                        else 0
                    )

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

        if not self.abort:
            print(f"File copied successfully from {resume_position} bytes onwards.")


if __name__ == "__main__":

    source_path = input("Enter the source file path: ").strip()
    destination_path = input(
        "Enter the destination file path (including network share path): "
    ).strip()

    if not os.path.exists(source_path):
        print("Source file does not exist.")
    else:
        try:
            c = Copier(False)
            c.copy_file_with_resume(source_path, destination_path)
        except Exception as e:
            print(f"An error occurred: {e}")
