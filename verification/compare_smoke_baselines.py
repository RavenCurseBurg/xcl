"""Replay #1056, #2230 and #2406 against one disposable Git history.

Run from an XCL clone containing the three PR commits below. No GitHub access,
game, or smoke run is needed.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

REVISIONS = (
    (1056, "dcef41877f5cf5550b34402e3ff24ac24e06b512"),
    (2230, "a156f8bbb737f79f9f63e594c9b39cb215c4a670"),
    (2406, "82bc4503a6d56f3ef88bc731c22f823d02150880"),
)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, encoding="utf-8")


def block(revision, frames):
    return (f"```\nxcl-smoke v1\ncommit: {revision}\ntitle: fixture\nseconds: 60\n"
            f"frames shown: {frames}\npeak commit: 1000 MB\ndevice removals: 0\ncrashes: 0\nexit: 0x0\n```\n")


def main():
    source = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        git(repo, "init", "-q", "-b", "main")
        revisions = []
        for label in ("old", "current", "candidate"):
            if label == "candidate":
                git(repo, "switch", "-q", "-c", label)
            git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "commit.gpgSign=false", "commit", "-q", "--allow-empty", "-m", label)
            revisions.append(git(repo, "rev-parse", "HEAD").strip())
        old, current, candidate = revisions
        git(repo, "update-ref", "refs/remotes/origin/main", current)
        blocks = {"old": block(old, 200), "old-ok": block(old, 100), "current": block(current, 100),
                  "current-high": block(current, 200), "dirty": block(current + " (uncommitted changes)", 100)}
        # Codes denote diagnostic categories. C = clean checkout; B = expected
        # base revision; F = fewer frames; D = duplicate baseline.
        cases = [
            (["current"], ("","","")), (["old-ok"], ("","","B")), (["old"], ("F","F","B")),
            (["old","current"], ("F","","")), (["current","old"], ("","","")),
            (["dirty"], ("C","C","CB")), (["dirty","current"], ("","","C")),
            (["current","dirty"], ("","","C")), (["current","current-high"], ("","","D")),
            (["current-high","current"], ("F","F","D")),
        ]
        diagnostics = {"C":"clean checkout", "B":"base commit", "F":"fewer frames", "D":"several main blocks"}
        files, body, script = repo / "files.tsv", repo / "body.md", repo / "pr_check.py"
        files.write_text(f"crates/xcl/src/gpu/dxbc.rs\tmodified\tfalse\t{candidate}\n", encoding="utf-8")
        prefix = "**Tested**\nSynthetic\n**Not tested**\nRetail game\n**AI use**\nOpenAI Codex (GPT-6)\n"
        for i, (number, revision) in enumerate(REVISIONS):
            script.write_bytes(subprocess.check_output(["git","-C",str(source),"show",revision+":scripts/pr_check.py"]))
            argv = [sys.executable, "-B", str(script), "--local", "--files", str(files),
                    "--body", str(body), "--head", candidate]
            if number == 2406:
                argv += ["--base", current]
            for order, expected in cases:
                body.write_text(prefix + "".join(blocks[name] for name in order) + block(candidate, 100), encoding="utf-8")
                result = subprocess.run(argv, cwd=repo, capture_output=True, text=True, timeout=30)
                reasons = [line for line in result.stdout.splitlines() if line.startswith(" -")]
                actual = {key for key, marker in diagnostics.items() if any(marker in reason for reason in reasons)}
                if actual != set(expected[i]) or len(reasons) != len(expected[i]) or result.returncode != int(bool(reasons)):
                    raise AssertionError((number, order, expected[i], result))
            print(f"#{number}: {len(cases)} baseline cases passed", flush=True)


if __name__ == "__main__":
    main()
