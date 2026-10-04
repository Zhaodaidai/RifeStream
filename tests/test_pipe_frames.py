import ast
import ctypes
from pathlib import Path
from types import SimpleNamespace
import unittest


class PipeFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        script = Path(__file__).resolve().parent.parent / "vs" / "rife_stream.vpy"
        tree = ast.parse(script.read_text(encoding="utf-8"))
        functions = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "copy_plane"
        ]
        namespace = {"ctypes": ctypes, "vs": SimpleNamespace(VideoFrame=object)}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(script), "exec"), namespace)
        cls.copy_plane = staticmethod(namespace["copy_plane"])

    def copy_to_plane(self, width: int, height: int, stride: int) -> bytearray:
        destination = bytearray([255] * (stride * height))
        source = memoryview(bytearray(range(width * height)))
        frame = SimpleNamespace(
            get_write_ptr=lambda plane: ctypes.c_void_p(
                ctypes.addressof(ctypes.c_ubyte.from_buffer(destination))
            ),
            get_stride=lambda plane: stride,
        )
        self.copy_plane(frame, 0, source, width, height)
        return destination

    def test_contiguous_plane(self) -> None:
        self.assertEqual(self.copy_to_plane(4, 3, 4), bytearray(range(12)))

    def test_padded_plane_preserves_padding(self) -> None:
        self.assertEqual(
            self.copy_to_plane(3, 2, 5),
            bytearray([0, 1, 2, 255, 255, 3, 4, 5, 255, 255]),
        )


if __name__ == "__main__":
    unittest.main()
