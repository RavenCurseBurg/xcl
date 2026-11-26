from pathlib import Path
from copy import deepcopy
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


SCRIPT = Path(__file__).resolve().with_name("gen_rdna2.py")
SPEC = """<Spec>
  <Document><Copyright>Synthetic test</Copyright><License>MIT</License><ReleaseDate>test</ReleaseDate></Document>
  <ISA>
    <Architecture><ArchitectureName>AMD RDNA 2</ArchitectureName></Architecture>
    <Encodings><Encoding>
      <EncodingName>ENC_TEST</EncodingName><BitCount>32</BitCount>
      <EncodingIdentifierMask>0</EncodingIdentifierMask>
      <EncodingIdentifiers><EncodingIdentifier>0</EncodingIdentifier></EncodingIdentifiers>
      <MicrocodeFormat><BitMap/></MicrocodeFormat>
    </Encoding></Encodings>
    <Instructions><Instruction>
      <InstructionName>S_TEST_BRANCH</InstructionName>
      <InstructionFlags>
        <IsBranch>{true}</IsBranch><IsConditionalBranch>TRUE</IsConditionalBranch>
        <IsProgramTerminator>{true}</IsProgramTerminator><IsImmediatelyExecuted>{false}</IsImmediatelyExecuted>
      </InstructionFlags>
      <InstructionEncodings><InstructionEncoding>
        <EncodingName>ENC_TEST</EncodingName><EncodingCondition>default</EncodingCondition>
        <Opcode>0</Opcode><Operands/>
      </InstructionEncoding></InstructionEncodings>
    </Instruction></Instructions>
  </ISA>
</Spec>"""


class InstructionFlagTests(unittest.TestCase):
    def test_every_mask_survives_xml_whitespace_and_encoding(self):
        flags = (("IsBranch", 1), ("IsConditionalBranch", 2), ("IsIndirectBranch", 4),
                 ("IsProgramTerminator", 8), ("IsImmediatelyExecuted", 16))
        spec = ET.fromstring(SPEC.format(true="TRUE", false="FALSE"))
        instructions = spec.find("ISA/Instructions")
        template = instructions.find("Instruction")
        instructions.remove(template)
        for mask in range(32):
            instruction = deepcopy(template)
            instruction.find("InstructionName").text = f"S_MASK_{mask:02}"
            instruction.find("InstructionEncodings/InstructionEncoding/Opcode").text = str(mask)
            fields = instruction.find("InstructionFlags")
            fields.clear()
            for tag, bit in flags:
                ET.SubElement(fields, tag).text = "TRUE" if mask & bit else "FALSE"
            instructions.append(instruction)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "isa.xml"
            output = Path(tmp) / "spec.rs"
            command = [sys.executable, "-B", str(SCRIPT), str(source), str(output)]
            source.write_bytes(ET.tostring(spec, encoding="utf-8"))
            subprocess.run(command, capture_output=True, check=True)
            expected = output.read_bytes()
            found = re.findall(rb'name: "S_MASK_(\d+)", flags: (\d+),', expected)
            self.assertEqual([(mask, mask) for mask in range(32)],
                             [(int(name), int(value)) for name, value in found])
            for field in instructions.findall("Instruction/InstructionFlags/*"):
                field.text = "\tTrUe\r\n" if field.text == "TRUE" else "\nFaLsE\t"
            for encoding in ("utf-8", "utf-16"):
                with self.subTest(encoding=encoding):
                    source.write_bytes(ET.tostring(spec, encoding=encoding))
                    subprocess.run(command, capture_output=True, check=True)
                    self.assertEqual(expected, output.read_bytes())

    def test_xml_whitespace_does_not_change_instruction_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "isa.xml"
            output = Path(tmp) / "spec.rs"

            def generate(true, false):
                source.write_text(SPEC.format(true=true, false=false), encoding="utf-8")
                subprocess.run([sys.executable, "-B", str(SCRIPT), str(source), str(output)], capture_output=True, check=True)
                return output.read_bytes()

            plain = generate("TRUE", "FALSE")
            self.assertIn(b'name: "S_TEST_BRANCH", flags: 11,', plain)
            self.assertEqual(generate(" \n true\t ", " false\n "), plain)


if __name__ == "__main__":
    unittest.main()
