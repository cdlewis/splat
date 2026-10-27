"""Exercise standalone rodata routing through a complete Splat extraction."""

import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

import yaml


class RodataRoutingTests(unittest.TestCase):
    def extract(self, source, disassemble_all=True, compiler="IDO"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "input.bin").write_bytes(
            struct.pack(">4I", 0x03E00008, 0, 0x12345678, 0)
        )
        (root / "symbols.txt").write_text(
            "test_func = 0x80000000; // type:func\n"
            "test_data = 0x80000008; // force_not_migration:True\n"
        )
        if source is not None:
            (root / "src").mkdir()
            (root / "src/test.c").write_text(source)
        config = {
            "name": "rodata routing",
            "options": {
                "basename": "test",
                "target_path": "input.bin",
                "base_path": ".",
                "platform": "n64",
                "compiler": compiler,
                "symbol_addrs_path": "symbols.txt",
                "disassemble_all": disassemble_all,
                "use_legacy_include_asm": False,
            },
            "segments": [
                {
                    "name": "test",
                    "type": "code",
                    "start": 0,
                    "vram": 0x80000000,
                    "subsegments": [[0, "c", "test"], [8, ".rodata", "test"]],
                },
                [16],
            ],
        }
        (root / "config.yaml").write_text(yaml.safe_dump(config))
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent / "src")
        result = subprocess.run(
            [sys.executable, "-m", "splat", "split", "config.yaml"],
            cwd=root,
            check=False,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return root

    def test_c_rodata_reference_goes_to_matchings(self):
        for compiler in ("IDO", "GCC"):
            with self.subTest(compiler=compiler):
                root = self.extract(
                    "void test_func(void) {}\nconst int test_data = 0x12345678;\n",
                    compiler=compiler,
                )
                self.assertTrue((root / "asm/matchings/test/test_data.s").is_file())
                self.assertFalse((root / "asm/nonmatchings/test/test_data.s").exists())

    def test_explicit_assembly_rodata_stays_nonmatching(self):
        sources = {
            "IDO": '#pragma GLOBAL_ASM("asm/nonmatchings/test/test_data.s")\n',
            "GCC": 'INCLUDE_RODATA("asm/nonmatchings/test", test_data);\n',
        }
        for compiler, source in sources.items():
            with self.subTest(compiler=compiler):
                root = self.extract(
                    "void test_func(void) {}\n" + source, compiler=compiler
                )
                self.assertTrue((root / "asm/nonmatchings/test/test_data.s").is_file())
                self.assertFalse((root / "asm/matchings/test/test_data.s").exists())

    def test_new_c_file_keeps_assembly_rodata_nonmatching(self):
        root = self.extract(None)
        self.assertTrue((root / "asm/nonmatchings/test/test_data.s").is_file())
        self.assertIn("test_data", (root / "src/test.c").read_text())

    def test_matched_rodata_is_not_emitted_without_disassemble_all(self):
        root = self.extract("void test_func(void) {}\n", disassemble_all=False)
        self.assertFalse((root / "asm/matchings/test/test_data.s").exists())
        self.assertFalse((root / "asm/nonmatchings/test/test_data.s").exists())


if __name__ == "__main__":
    unittest.main()
