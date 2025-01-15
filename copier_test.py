from copier import *
import fs
import pytest


# @pytest
def test_find_resume_position_in_second_half():

    mem_fs = fs.open_fs("mem://")
    with mem_fs.open("test_dst.bin", "wb") as f_dst:
        with mem_fs.open("test_src.bin", "wb") as f_src:
            for _ in range(0, 7):
                f_src.write(b"\x01")
                f_dst.write(b"\x01")
            for _ in range(0, 3):
                f_src.write(b"\x01")
                f_dst.write(b"\x00")

            c = Copier(mem_fs)

            _pos = c.find_resume_position(f_src, f_dst, block_size=2)
            assert _pos == 6


# def test_find_resume_position_in_first_half():

#     mem_fs = fs.open_fs("mem://")
#     with mem_fs.open("mem_test.xml", "wb") as f:
#         for _ in range(0, 3):
#             f.write(b"\x01")
#         for _ in range(0, 7):
#             f.write(b"\x00")

#     c = Copier(mem_fs)

#     _pos = c.find_resume_position("mem_test.xml", block_size=2)
#     assert _pos == 2


# c = Copier(check_all_files=False)
# _pos = c.find_resume_position(
#     "o:\TMOI_DataStorage\Tuner-Recordings\RF-Catcher\DAB-DAB_S-ANHALT_to_SACHSEN_MDR\DAB-DAB_S-ANHALT_to_SACHSEN_MDR.7z.111__",
#     block_size=1024,
# )
# print(_pos)

# c.copy_file_with_resume(
#     r"d:\projects\IAV\tuner_middleware\RF-CATCHER\recordings\DAB-DAB_S-ANHALT_to_SACHSEN_MDR\DAB-DAB_S-ANHALT_to_SACHSEN_MDR.7z.114",
#     r"o:\TMOI_DataStorage\Tuner-Recordings\RF-Catcher\DAB-DAB_S-ANHALT_to_SACHSEN_MDR\DAB-DAB_S-ANHALT_to_SACHSEN_MDR.7z.114",
# )

c = Copier(check_all_files=True)
c.copy_directory(
    r"d:\projects\IAV\tuner_middleware\RF-CATCHER\recordings\DAB-DAB_S-ANHALT_to_SACHSEN_MDR",
    r"o:\TMOI_DataStorage\Tuner-Recordings\RF-Catcher\DAB-DAB_S-ANHALT_to_SACHSEN_MDR",
    start_file_name="DAB-DAB_S-ANHALT_to_SACHSEN_MDR.7z.121",
)

# test_find_resume_position_in_first_half()
# test_find_resume_position_in_second_half()
