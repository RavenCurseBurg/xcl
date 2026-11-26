from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parent / "re" / "record_writers.py"


class RecordWriterTests(unittest.TestCase):
    def test_only_completed_writer_contributes_its_first_stored_header(self):
        listing_text = """\
   1000: mov 0x18(%rcx),%rax
   1004: cmp 0x30(%rcx),%rax
   1008: jae 1030
   100c: mov 0x10(%rcx),%edx
   1010: movl $0x37,0x0(%rax)
   1014: add $0x20,%rax
   1018: mov %rax,0x18(%rcx)
   101c: ret
   1030: call *0x40(%rbx)
   2000: mov 0x18(%rcx),%rax
   2004: cmp 0x30(%rcx),%rax
   2008: jae 2030
   200c: movl $0x99,(%rax)
   2010: ret
   2030: call *0x40(%rbx)
"""
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path(tmp) / "two-sites.txt"
            listing.write_text(listing_text, encoding="ascii")
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), str(listing)],
                                    capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines()[0], "1 record write sites")
        self.assertRegex(result.stdout, r"header imm 37\s+length 32 B\s+bound \+0x30\s+fallback slot 8")

    def test_cursor_store_must_be_on_the_fast_path(self):
        for boundary in ("ret", "nop"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as tmp:
                listing = Path(tmp) / "synthetic.asm"
                listing.write_text(
                    "   180001000: mov 0x18(%rcx),%rax\n"
                    "   180001004: cmp 0x30(%rcx),%rax\n"
                    f"   180001008: jae {'180001030' if boundary == 'ret' else '180001010'}\n"
                    "   18000100a: movl $0x1234,(%rax)\n"
                    f"   18000100e: {boundary}\n"
                    "   180001010: add $0x20,%rax\n"
                    "   180001014: mov %rax,0x18(%rcx)\n"
                    "   180001018: ret\n"
                    "   180001030: call *0x40(%rbx)\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT), str(listing)],
                    capture_output=True, text=True, check=True,
                )
                self.assertEqual("0 record write sites", result.stdout.strip())

    def test_branch_targets_with_and_without_hex_prefix(self):
        for target in ("180001030 <fallback>", "0x180001030 <fallback>"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                listing = Path(tmp) / "synthetic.asm"
                listing.write_text(
                    "   180001000: mov 0x18(%rcx),%rax\n"
                    "   180001004: cmp 0x30(%rcx),%rax\n"
                    f"   180001008: jae {target}\n"
                    "   18000100a: movl $0x1234,(%rax)\n"
                    "   180001010: add $0x20,%rax\n"
                    "   180001014: mov %rax,0x18(%rcx)\n"
                    "   180001018: ret\n"
                    "   180001030: call *0x40(%rbx)\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT), str(listing)],
                    capture_output=True, text=True, check=True,
                )
                self.assertIn("1 record write sites", result.stdout)
                self.assertRegex(
                    result.stdout,
                    r"header imm 1234\s+length 32 B  bound \+0x30  fallback slot 8",
                )

    def test_header_comes_from_the_first_store_at_the_record_base(self):
        cases = (
            (("mov 0x10(%rcx),%edx", "movl $0x37,(%rax)"), "imm 37"),
            (("movl $0x37,0x0(%rax)",), "imm 37"),
            (("mov 0x10(%rcx),%r8d", "mov 0x344(%rcx),%edx",
              "mov %edx,0x0(%rax)", "movl $0x37,(%rax)"), "list+344"),
            (("mov 0x10(%rcx),%edx", "xor %edx,%edx",
              "mov %edx,(%rax)", "movl $0x37,(%rax)"), "?"),
        )
        for body, header in cases:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as tmp:
                instructions = (
                    "mov 0x18(%rcx),%rax", "cmp 0x30(%rcx),%rax", "jae 180001030",
                    *body, "add $0x20,%rax", "mov %rax,0x18(%rcx)", "ret",
                )
                listing = Path(tmp) / "synthetic.asm"
                listing.write_text(
                    "".join(f"   {0x180001000 + 4 * i:x}: {ins}\n"
                            for i, ins in enumerate(instructions))
                    + "   180001030: call *0x40(%rbx)\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT), str(listing)],
                    capture_output=True, text=True, check=True,
                )
                self.assertIn(f"header {header:18} length 32 B", result.stdout)


if __name__ == "__main__":
    unittest.main()
