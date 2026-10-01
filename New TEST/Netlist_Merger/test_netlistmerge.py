import tempfile
import unittest
from pathlib import Path

from netlistmerge import XMLNetlistMapper


class InputCompatibilityTests(unittest.TestCase):
    def test_reviewed_metadata_decimal_coordinates_and_exact_output(self):
        raw = '''ANNOTATION CONNECTIVITY
Net 7 (Net-7):
  Via V001 @ (10, 20) px; layers [0, 1]
  Pad L0:pad:row1:part0 (Instance ID 1) @ (10.125, 20.500) px
  Pad L1:pad:row2:part0 (Instance ID 2) @ (10.125, 20.500) px
  Pad L0:pad:row3:part0 (Instance ID 3) @ (100.000, 100.000) px
  Pad L0:pad:row4:part0 (Instance ID 4) @ (900.000, 900.000) px
  Copper: L0:trace:row5:part0
Net 8 (Net-8):
  Via V002 @ (10, 20) px; layers [0, 1]
Net 9 (Net-9):
  Pad L0:pad:row6:part0 (Instance ID 6) @ (10.125, 20.500) px
  Status: 1 annotated terminal(s); retained for review
'''
        pins = [{'ref': 'R1', 'pin': '2', 'px': 10, 'py': 20},
                {'ref': 'C1', 'pin': '1', 'px': 100, 'py': 100}]
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/'raw.txt', Path(folder)/'out.txt'
            source.write_text(raw)
            XMLNetlistMapper(100, 100).translate_netlist(source, pins, target)
            self.assertEqual(target.read_text(),
                'PCB LOGICAL NETLIST (Cleaned & Mapped)\n'
                '==================================================\n\n'
                'Net 7:\n  C1-1\n  <--->  R1-2\n')

    def test_original_format(self):
        self.assertEqual(XMLNetlistMapper.read_raw_nets(
            'PCB RAW NETLIST\nNet 12:\n  Pad [Layer 0 @ (12, 34)]\n'
            '  <--->  Pad [Layer 3 @ (56, 78)]\n'),
            [('12', [(12.0, 34.0), (56.0, 78.0)])])

    def test_rejects_bad_pad_and_duplicate_net(self):
        for raw in ('Net 1 (Net-1):\nPad broken', 'Net 1:\nNet 1:'):
            with self.assertRaises(ValueError):
                XMLNetlistMapper.read_raw_nets(raw)


if __name__ == '__main__':
    unittest.main()
