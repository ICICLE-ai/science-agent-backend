import ctypes
from pathlib import Path

import numpy as np


HID = ctypes.c_longlong
HSIZE = ctypes.c_ulonglong
H5P_DEFAULT = HID(0)
H5S_ALL = HID(0)
H5F_ACC_RDONLY = 0x0000
H5F_ACC_TRUNC = 0x0002


class NativeHDF5:
    """Call the HDF5 library bundled with ArrayMorph to avoid mixed HDF5 ABIs."""

    def __init__(self):
        import arraymorph

        package_root = Path(arraymorph.__file__).resolve().parent.parent
        candidates = sorted(
            (package_root / "arraymorph.libs").glob("libhdf5-*.so.*")
        )
        if not candidates:
            raise RuntimeError("ArrayMorph bundled HDF5 library was not found")
        library_dir = candidates[0].parent
        try:
            for pattern in ("libaec-*.so.*", "libsz-*.so.*"):
                dependency = next(library_dir.glob(pattern))
                ctypes.CDLL(str(dependency), mode=ctypes.RTLD_GLOBAL)
            self.lib = ctypes.CDLL(
                str(candidates[0]),
                mode=ctypes.RTLD_GLOBAL,
            )
        except (OSError, StopIteration) as exc:
            raise RuntimeError(
                "ArrayMorph bundled HDF5 dependencies could not be loaded"
            ) from exc
        self._declare_functions()
        self._check_status(self.lib.H5open(), "H5open")
        try:
            self.uint8_type = HID.in_dll(
                self.lib,
                "H5T_NATIVE_UCHAR_g",
            ).value
        except ValueError as exc:
            raise RuntimeError("Bundled HDF5 uint8 type is unavailable") from exc

    def _declare_functions(self):
        self.lib.H5open.argtypes = []
        self.lib.H5open.restype = ctypes.c_int
        self.lib.H5Fcreate.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint,
            HID,
            HID,
        ]
        self.lib.H5Fcreate.restype = HID
        self.lib.H5Fopen.argtypes = [ctypes.c_char_p, ctypes.c_uint, HID]
        self.lib.H5Fopen.restype = HID
        self.lib.H5Fclose.argtypes = [HID]
        self.lib.H5Fclose.restype = ctypes.c_int
        self.lib.H5Screate_simple.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(HSIZE),
            ctypes.POINTER(HSIZE),
        ]
        self.lib.H5Screate_simple.restype = HID
        self.lib.H5Sclose.argtypes = [HID]
        self.lib.H5Sclose.restype = ctypes.c_int
        self.lib.H5Dcreate2.argtypes = [
            HID,
            ctypes.c_char_p,
            HID,
            HID,
            HID,
            HID,
            HID,
        ]
        self.lib.H5Dcreate2.restype = HID
        self.lib.H5Dopen2.argtypes = [HID, ctypes.c_char_p, HID]
        self.lib.H5Dopen2.restype = HID
        self.lib.H5Dwrite.argtypes = [
            HID,
            HID,
            HID,
            HID,
            HID,
            ctypes.c_void_p,
        ]
        self.lib.H5Dwrite.restype = ctypes.c_int
        self.lib.H5Dread.argtypes = [
            HID,
            HID,
            HID,
            HID,
            HID,
            ctypes.c_void_p,
        ]
        self.lib.H5Dread.restype = ctypes.c_int
        self.lib.H5Dclose.argtypes = [HID]
        self.lib.H5Dclose.restype = ctypes.c_int

    @staticmethod
    def _check_id(value, operation):
        if value < 0:
            raise RuntimeError(f"ArrayMorph HDF5 operation failed: {operation}")
        return value

    @staticmethod
    def _check_status(value, operation):
        if value < 0:
            raise RuntimeError(f"ArrayMorph HDF5 operation failed: {operation}")

    @staticmethod
    def _dims(shape):
        return (HSIZE * len(shape))(*shape)

    def write_uint8(self, file_name: str, dataset_name: str, data: np.ndarray):
        array = np.ascontiguousarray(data, dtype=np.uint8)
        dims = self._dims(array.shape)
        file_id = self._check_id(
            self.lib.H5Fcreate(
                file_name.encode("utf-8"),
                H5F_ACC_TRUNC,
                H5P_DEFAULT,
                H5P_DEFAULT,
            ),
            "H5Fcreate",
        )
        space_id = -1
        dataset_id = -1
        try:
            space_id = self._check_id(
                self.lib.H5Screate_simple(
                    len(array.shape),
                    dims,
                    None,
                ),
                "H5Screate_simple",
            )
            dataset_id = self._check_id(
                self.lib.H5Dcreate2(
                    file_id,
                    dataset_name.encode("utf-8"),
                    self.uint8_type,
                    space_id,
                    H5P_DEFAULT,
                    H5P_DEFAULT,
                    H5P_DEFAULT,
                ),
                "H5Dcreate2",
            )
            self._check_status(
                self.lib.H5Dwrite(
                    dataset_id,
                    self.uint8_type,
                    H5S_ALL,
                    H5S_ALL,
                    H5P_DEFAULT,
                    array.ctypes.data_as(ctypes.c_void_p),
                ),
                "H5Dwrite",
            )
        finally:
            if dataset_id >= 0:
                self.lib.H5Dclose(dataset_id)
            if space_id >= 0:
                self.lib.H5Sclose(space_id)
            self.lib.H5Fclose(file_id)

    def read_uint8(
        self,
        file_name: str,
        dataset_name: str,
        shape: tuple[int, ...],
    ) -> np.ndarray:
        output = np.empty(shape, dtype=np.uint8)
        file_id = self._check_id(
            self.lib.H5Fopen(
                file_name.encode("utf-8"),
                H5F_ACC_RDONLY,
                H5P_DEFAULT,
            ),
            "H5Fopen",
        )
        dataset_id = -1
        try:
            dataset_id = self._check_id(
                self.lib.H5Dopen2(
                    file_id,
                    dataset_name.encode("utf-8"),
                    H5P_DEFAULT,
                ),
                "H5Dopen2",
            )
            self._check_status(
                self.lib.H5Dread(
                    dataset_id,
                    self.uint8_type,
                    H5S_ALL,
                    H5S_ALL,
                    H5P_DEFAULT,
                    output.ctypes.data_as(ctypes.c_void_p),
                ),
                "H5Dread",
            )
        finally:
            if dataset_id >= 0:
                self.lib.H5Dclose(dataset_id)
            self.lib.H5Fclose(file_id)
        return output
