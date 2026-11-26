from contextlib import redirect_stdout
import io
from pathlib import Path
import runpy
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parent / "re" / "check_layout.py"


class CheckLayoutRootlessTests(unittest.TestCase):
    def test_mixed_directory_disassembles_only_the_shader_with_a_root_signature(self):
        def container(tag, payload):
            chunk = tag + struct.pack("<I", len(payload)) + payload
            return struct.pack("<4s16sIIII", b"DXBC", bytes(16), 1, 36 + len(chunk), 1, 36) + chunk

        signature = struct.pack("<6I3I2I", 1, 1, 24, 0, 0, 0, 2, 0, 36, 0, 0)
        listing = "s_mov_b32 s4, s0\ns_and_b32 s5, s1, 0xff\ns_load_dword s6, s[4:5], 0x0\n"
        with tempfile.TemporaryDirectory() as tmp:
            for rooted, rootless in [("01.dxbc", "00.dxbc"), ("00.dxbc", "01.dxbc")]:
                with self.subTest(rooted=rooted):
                    (Path(tmp) / rooted).write_bytes(container(b"RTS0", signature))
                    (Path(tmp) / rootless).write_bytes(container(b"STAT", bytes(4)))
                    result = subprocess.CompletedProcess([], 0, stdout=listing, stderr="")
                    output = io.StringIO()
                    with patch.object(sys, "argv", [str(SCRIPT), tmp]), redirect_stdout(output), \
                            patch.object(subprocess, "run", return_value=result) as disasm:
                        runpy.run_path(str(SCRIPT), run_name="__main__")
                    disasm.assert_called_once()
                    self.assertEqual(disasm.call_args.args[0][1:], ["disasm", str(Path(tmp) / rooted)])
                    self.assertEqual(output.getvalue().splitlines(), [
                        rootless + " no embedded root signature (RTS0); skipped",
                        "loads on parameter boundaries: 1, off: 0",
                    ])

    def test_reports_each_shader_without_an_embedded_root_signature(self):
        chunk = struct.pack("<4sI", b"STAT", 4) + bytes(4)
        container = struct.pack("<4s16sIIII", b"DXBC", bytes(16), 1, 36 + len(chunk), 1, 36)
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("00.dxbc", "01.dxbc"):
                (Path(tmp) / name).write_bytes(container + chunk)
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPT), tmp], capture_output=True, text=True,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                "00.dxbc no embedded root signature (RTS0); skipped",
                "01.dxbc no embedded root signature (RTS0); skipped",
                "loads on parameter boundaries: 0, off: 0",
            ],
            result.stdout.splitlines(),
        )


if __name__ == "__main__":
    unittest.main()
