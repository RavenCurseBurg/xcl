from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parent / "re" / "record_writers.py"


class RecordWriterTests(unittest.TestCase):
    def test_cmpxchg_invalidates_only_possible_cursor_writes(self):
        cases = (
            ("rdx", "cmpxchgl %r8d,%edx", "None"),
            ("rax", "lock cmpxchgq %r8,(%rbx)", "None"),
            ("rdx", "lock cmpxchg8b (%rbx)", "None"),
            ("rdx", "cmpxchg16b (%rbx)", "None"),
            ("rdx", "cmpxchgq %rdx,%r9", "32"),
            ("rdx", "cmpq %r8,%rdx", "32"),
        )
        for dst, instruction, expected in cases:
            with self.subTest(instruction=instruction), tempfile.TemporaryDirectory() as tmp:
                listing = Path(tmp) / "synthetic.asm"
                listing.write_text(
                    "   1000: mov 0x18(%rcx),%r10\n"
                    "   1004: cmp 0x30(%rcx),%r10\n"
                    "   1008: jae 1030\n"
                    f"   100c: lea 0x20(%r10),%{dst}\n"
                    f"   1010: {instruction}\n"
                    f"   1014: mov %{dst},0x18(%rcx)\n"
                    "   1018: ret\n"
                    "   1030: call *0x40(%rbx)\n",
                    encoding="ascii",
                )
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT), str(listing)],
                    capture_output=True, text=True, check=True,
                )
                self.assertIn(f"length {expected} B", result.stdout)

    def test_lea_length_matches_pointer_and_stored_register(self):
        cases = (
            (
                "unrelated_base_and_dest_lea_ignored",
                "   180002000: mov 0x18(%rcx),%rax\n"
                "   180002004: cmp 0x30(%rcx),%rax\n"
                "   180002008: jae 180002030 <fallback>\n"
                "   18000200a: movl $0x5678,(%rax)\n"
                "   180002010: lea 0x20(%rax),%rdx\n"
                "   180002014: lea 0x18(%rax),%r9\n"
                "   180002018: lea 0x10(%rsp),%rsi\n"
                "   18000201c: mov %rdx,0x18(%rcx)\n"
                "   180002020: ret\n"
                "   180002030: call *0x40(%rbx)\n",
                "32",
            ),
            (
                "unrelated_lea_without_cursor_lea_stays_none",
                "   180003000: mov 0x18(%rcx),%rax\n"
                "   180003004: cmp 0x30(%rcx),%rax\n"
                "   180003008: jae 180003030 <fallback>\n"
                "   18000300a: movl $0x5678,(%rax)\n"
                "   180003010: lea 0x10(%rsp),%rsi\n"
                "   180003014: add %r8,%rax\n"
                "   180003017: mov %rax,0x18(%rcx)\n"
                "   18000301b: ret\n"
                "   180003030: call *0x40(%rbx)\n",
                "None",
            ),
            (
                "intervening_add_to_lea_dst_clears_length",
                "   180004000: mov 0x18(%rcx),%rax\n"
                "   180004004: cmp 0x30(%rcx),%rax\n"
                "   180004008: jae 180004030 <fallback>\n"
                "   18000400a: movl $0x5678,(%rax)\n"
                "   180004010: lea 0x20(%rax),%rdx\n"
                "   180004014: add %r8,%rdx\n"
                "   180004017: mov %rdx,0x18(%rcx)\n"
                "   18000401b: ret\n"
                "   180004030: call *0x40(%rbx)\n",
                "None",
            ),
            (
                "intervening_subreg_write_to_lea_dst_clears_length",
                "   180005000: mov 0x18(%rcx),%rax\n"
                "   180005004: cmp 0x30(%rcx),%rax\n"
                "   180005008: jae 180005030 <fallback>\n"
                "   18000500a: movl $0x5678,(%rax)\n"
                "   180005010: lea 0x20(%rax),%rdx\n"
                "   180005014: add $0x8,%edx\n"
                "   180005017: mov %rdx,0x18(%rcx)\n"
                "   18000501b: ret\n"
                "   180005030: call *0x40(%rbx)\n",
                "None",
            ),
            (
                "pointer_mutated_before_lea_clears_length",
                "   180006000: mov 0x18(%rcx),%rax\n"
                "   180006004: cmp 0x30(%rcx),%rax\n"
                "   180006008: jae 180006030 <fallback>\n"
                "   18000600a: movl $0x5678,(%rax)\n"
                "   180006010: add %r8,%rax\n"
                "   180006013: lea 0x20(%rax),%rdx\n"
                "   180006017: mov %rdx,0x18(%rcx)\n"
                "   18000601b: ret\n"
                "   180006030: call *0x40(%rbx)\n",
                "None",
            ),
            (
                "memory_store_through_lea_dst_preserves_length",
                "   180007000: mov 0x18(%rcx),%rax\n"
                "   180007004: cmp 0x30(%rcx),%rax\n"
                "   180007008: jae 180007030 <fallback>\n"
                "   18000700a: movl $0x5678,(%rax)\n"
                "   180007010: lea 0x20(%rax),%rdx\n"
                "   180007014: movl $0x1,-0x4(%rdx)\n"
                "   18000701b: mov %rdx,0x18(%rcx)\n"
                "   18000701f: ret\n"
                "   180007030: call *0x40(%rbx)\n",
                "32",
            ),
        )
        for name, asm, expected_len in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                listing = Path(tmp) / "synthetic.asm"
                listing.write_text(asm, encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPT), str(listing)],
                    capture_output=True, text=True, check=True,
                )
                self.assertIn("1 record write sites", result.stdout)
                self.assertRegex(
                    result.stdout,
                    rf"header imm 5678\s+length {expected_len} B  bound \+0x30  fallback slot 8",
                )

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
