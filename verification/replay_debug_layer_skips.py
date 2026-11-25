"""Replay the two debug-layer skip messages against the #2489 Windows test runner.

Run this script from an XCL checkout containing #2489 and its parent. Python,
Git, Windows PowerShell, and PowerShell 7 must be on PATH. Only a native Cargo
stand-in runs. The Rust tests and the Windows DLL installation are untouched.
"""
from collections import Counter
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

repo = Path.cwd()
ref = "9a85479b74c66dd1b8b241dbee79630c49d6246f"
def source(revision):
    return subprocess.check_output(["git", "-C", str(repo), "show", f"{revision}:crates/xcl/tests/e2e.rs"]).decode()

new, old = source(ref), source(ref + "^")
runner = subprocess.check_output(["git", "-C", str(repo), "show", f"{ref}:scripts/test.ps1"])
previous_format = re.search(r'"(SKIPPED the title[^"]+)"', old)[1]
current_format = re.search(r'format!\("(SKIPPED [^"]+)"\)', new)[1]
names = re.findall(r"fn (\w+)\(\) \{\s+title_under_the_debug_layer\((true|false)\);", new)
dlls = re.search(r'for dll in \["([^"]+)", "([^"]+)"\]', new).groups()
fallback = re.search(r'thread.name\(\).unwrap_or\("([^"]+)"\)', new)[1]
assert len(names) == 2 and len(set(dlls)) == 2
for shell in ("powershell", "pwsh"):
    exe = shutil.which(shell)
    assert exe
    for label, form in (("parent", previous_format), ("head", current_format)):
        for code in (0, 101):
            with tempfile.TemporaryDirectory() as temp:
                tmp = Path(temp)
                scripts = tmp / "scripts"
                scripts.mkdir()
                (scripts / "test.ps1").write_bytes(runner)
                lines = [form.format(test=name, dred=dred, dll=dll) for name, dred in names for dll in dlls]
                lines += [form.format(test=fallback, dred="false", dll=dlls[0]),
                          "SKIPPED independent_fixture: no wave64"]
                (tmp / "lines.txt").write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
                (tmp / "cargo.cmd").write_bytes(
                    b'@echo off\r\nif "%1"=="build" exit /b 0\r\nif not "%1"=="test" exit /b 127\r\n'
                    b'type "%~dp0lines.txt" 1>&2\r\nexit /b %FIXTURE_EXIT%\r\n')
                env = dict(os.environ, PATH=str(tmp) + os.pathsep + os.environ["PATH"], FIXTURE_EXIT=str(code))
                run = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                      "-File", str(scripts / "test.ps1")], env=env,
                                     capture_output=True, text=True, timeout=35)
                output = run.stdout + run.stderr
                assert run.returncode == code, (shell, label, run.returncode, output)
                assert all(line in output for line in lines), (shell, label, output)
                summaries = re.findall(r"^GPU tests skipped on this adapter: (.+)$", output, re.M)
                assert len(summaries) == 1, output
                counts = Counter({k: int(v) for v, k in re.findall(r"(\d+) \(([^)]+)\)", summaries[0])})
                expected = Counter({"no wave64": 1})
                if label == "head":
                    expected.update({"no " + dlls[0]: 3, "no " + dlls[1]: 2})
                assert counts == expected, (shell, label, counts, expected, output)
                print(shell, label, code, dict(counts), flush=True)
