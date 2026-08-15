"""Contributing gate — makes README_BEFORE_CONTRIBUTING.md load-bearing.

The guide is enforced mechanically, not by goodwill. Three invariants:

  G1  every guard test the guide's §3 red-line table names must actually exist
      (a guide that references phantom tests is lying about its own defenses);
  G2  the AGENTS.md signal inventory must stay in sync with the contract
      classes really present in test_signal_contracts.py;
  G3  the baseline test count the guide advertises must equal the real suite
      (adding tests without bumping the guide makes the docs rot).

If these go red, the docs lied — fix the docs (or the code), never the gate.
The pre-commit hook (hooks/pre-commit) runs this suite on every src/tests
change, so the gate cannot be skipped by forgetting.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE_TEXT = (ROOT / "README_BEFORE_CONTRIBUTING.md").read_text(encoding="utf-8")
AGENTS_TEXT = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
SECTION3 = GUIDE_TEXT.split("## 3.")[1].split("## 4.")[0]


class TestGuideIsEnforced(unittest.TestCase):
    def test_G1_guard_tests_named_in_redline_table_exist(self):
        # Test files named by the guide (test_xxx / test_xxx.py)
        for tok in set(re.findall(r"\btest_[a-z0-9_]+(?:\.py)?\b", SECTION3)):
            fname = tok if tok.endswith(".py") else tok + ".py"
            self.assertTrue(
                (ROOT / "tests" / fname).is_file(),
                f"guide §3 names {tok!r} but tests/{fname} does not exist")

        # Contract ids (C4, C8, …) → a C<n>… class must exist in the contract suite
        tsc_src = (ROOT / "tests" / "test_signal_contracts.py").read_text(encoding="utf-8")
        have_cids = set(re.findall(r"^class C(\d+)", tsc_src, re.MULTILINE))
        for cid in set(re.findall(r"\bC(\d+)\b", SECTION3)):
            self.assertIn(cid, have_cids,
                          f"guide §3 references C{cid} but test_signal_contracts "
                          f"has no C{cid}* class")

        # TestCase classes named by the guide (TestPriorsYamlHygiene, TestSteer…)
        all_tests_src = "\n".join(
            f.read_text(encoding="utf-8") for f in sorted((ROOT / "tests").glob("test_*.py")))
        for cls in set(re.findall(r"\bTest[A-Z][A-Za-z0-9]+\b", SECTION3)):
            self.assertIn(f"class {cls}(", all_tests_src,
                          f"guide §3 names class {cls!r} but no test defines it")

    def test_G2_signal_inventory_stays_in_sync(self):
        inventory_rows = re.findall(r"^\|\s*\d+\s*\|", AGENTS_TEXT, re.MULTILINE)
        contract_classes = re.findall(
            r"^class C(\d+)", (ROOT / "tests" / "test_signal_contracts.py")
            .read_text(encoding="utf-8"), re.MULTILINE)
        self.assertEqual(
            len(inventory_rows), len(contract_classes),
            "AGENTS.md signal table and test_signal_contracts.py C-classes "
            f"disagree ({len(inventory_rows)} rows vs {len(contract_classes)} "
            "contracts) — add the inventory row AND the contract test together")

    def test_G3_guide_baseline_count_matches_suite(self):
        m = re.search(r"当前基线：\*\*(\d+)\s*tests", GUIDE_TEXT)
        self.assertIsNotNone(m, "guide §0 must state 当前基线：**<N> tests")
        advertised = int(m.group(1))
        actual = unittest.TestLoader().discover(str(ROOT / "tests")).countTestCases()
        self.assertEqual(
            advertised, actual,
            f"guide advertises {advertised} tests but the suite has {actual} — "
            "bump the baseline in README_BEFORE_CONTRIBUTING.md §0 (and the "
            "counts in AGENTS.md / README badges) in the same commit")


if __name__ == "__main__":
    unittest.main()
