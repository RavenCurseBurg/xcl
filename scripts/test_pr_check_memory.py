import unittest

from pr_check import check


HEAD = "1234567890abcdef"
MAIN = "abcdef1234567890"
BODY = "**Tested**\nSynthetic fixtures\n**Not tested**\nRetail titles\n**AI use**\nNone\n"
FILES = [("crates/xcl/src/config.rs", "modified", False, lambda: 10)]


def smoke(commit, peak):
    block = (
        f"```\nxcl-smoke v1\ncommit: {commit}\ntitle: synthetic\nseconds: 60\n"
        "exit: 0x0\nframes shown: 1000 (PresentX 1000)\ndevice removals: 0\ncrashes: 0\n"
    )
    if peak is not None:
        block += f"peak commit: {peak}\n"
    return block + "```\n"


def problems(main_peak, pr_peak):
    return check(BODY + smoke(MAIN, main_peak) + smoke(HEAD, pr_peak), HEAD, FILES, lambda sha: sha == MAIN)


class SmokeMemoryTests(unittest.TestCase):
    def test_both_runs_need_a_memory_measurement(self):
        for side in ("main", "PR"):
            for missing in (None, "", "n/a MB", "unknown"):
                with self.subTest(side=side, peak=missing):
                    peaks = (missing, "100 MB") if side == "main" else ("100 MB", missing)
                    self.assertTrue(problems(*peaks))

    def test_measured_memory_still_obeys_the_growth_limit(self):
        self.assertEqual([], problems("100 MB", "125 MB"))
        self.assertTrue(problems("100 MB", "126 MB"))


if __name__ == "__main__":
    unittest.main()
