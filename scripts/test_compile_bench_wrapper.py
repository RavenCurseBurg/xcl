from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("compile_bench.ps1")


@unittest.skipUnless(os.name == "nt", "uses a Windows native command stand-in")
class CompileBenchWrapperTests(unittest.TestCase):
    def test_only_this_runs_report_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cargo.cmd").write_text(
                '@echo off\n'
                'if "%XCL_FIXTURE_MODE%"=="skip" (echo test skipped: no DXC & exit /b 0)\n'
                'if "%XCL_FIXTURE_MODE%"=="error" exit /b 37\n'
                'if "%XCL_FIXTURE_MODE%"=="write" (\n'
                '  >"%XCL_COMPILE_BENCH_OUT%\\compile_bench.json" echo fresh\n'
                '  >"%XCL_COMPILE_BENCH_OUT%\\compile_bench.csv" echo rows\n'
                ')\n'
                'echo written: %XCL_COMPILE_BENCH_OUT%\\compile_bench.json, compile_bench.csv\n',
                encoding="ascii",
            )
            for shell in ("powershell.exe", "pwsh.exe"):
                executable = shutil.which(shell)
                if not executable:
                    continue
                out = root / (shell + " results")
                out.mkdir()
                report = out / "compile_bench.json"
                for mode, existing, status in (("skip", False, 1), ("skip", True, 1),
                                               ("error", True, 37), ("notice", False, 1),
                                               ("write", True, 0)):
                    with self.subTest(shell=shell, mode=mode, existing=existing):
                        report.unlink(missing_ok=True)
                        if existing:
                            report.write_bytes(b"previous")
                        paths = (root, Path(shutil.which("git")).parent, Path(os.environ["SystemRoot"]) / "System32")
                        env = dict(os.environ, PATH=os.pathsep.join(map(str, paths)),
                                   XCL_FIXTURE_MODE=mode)
                        result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
                                                 "-Set", "small", "-Out", str(out)], env=env, capture_output=True)
                        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
                        if mode == "write":
                            self.assertEqual(report.read_bytes().strip(), b"fresh")
                        elif existing:
                            self.assertEqual(report.read_bytes(), b"previous")
                        else:
                            self.assertFalse(report.exists())
