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

    def test_timestamp_reads_overwrite_only_their_output_registers(self):
        cases = (
            ("rdtsc", "rax", "r9", True, "None"),
            ("rdtsc", "r10", "rdx", False, "None"),
            ("rdtsc", "r10", "r9", False, "32"),
            ("rdtsc", "rax", "r9", False, "32"),
            ("rdtsc", "r10", "rcx", False, "32"),
            ("rdtscp", "rcx", "r9", True, "None"),
            ("rdtscp", "r10", "rax", False, "None"),
            ("rdtscp", "r10", "rdx", False, "None"),
            ("rdtscp", "r10", "r9", False, "32"),
        )
        for op, base, dst, before, expected in cases:
            with self.subTest(case=(op, base, dst, before)), tempfile.TemporaryDirectory() as tmp:
                lea = f"lea 0x20(%{base}),%{dst}"
                first, second = (op, lea) if before else (lea, op)
                listing = Path(tmp) / "synthetic.asm"
                listing.write_text(
                    f"   1000: mov 0x18(%rdi),%{base}\n"
                    f"   1004: cmp 0x30(%rdi),%{base}\n"
                    "   1008: jae 1030\n"
                    f"   100c: {first}\n"
                    f"   1010: {second}\n"
                    f"   1014: mov %{dst},0x18(%rdi)\n"
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


if __name__ == "__main__":
    unittest.main()
