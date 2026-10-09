import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import pikepdf


spec = importlib.util.spec_from_file_location('scan', Path(__file__).with_name('scan.py'))
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.spool = Path(self.temp.name) / 'spool'
        self.consume = Path(self.temp.name) / 'consume'

    def run_scan(self, count, status):
        def scanimage(command, **kwargs):
            self.assertEqual(command[command.index('--device-name') + 1], 'brother5:net1;dev0')
            self.assertEqual(command[command.index('--source') + 1], 'Automatic Document Feeder(center aligned)')
            self.assertEqual(command[command.index('--mode') + 1], 'True Gray')
            self.assertEqual(command[command.index('--resolution') + 1], '300')
            self.assertNotIn('env', kwargs)
            pattern = next(arg.removeprefix('--batch=') for arg in command if arg.startswith('--batch='))
            for page in range(1, count + 1):
                Image.new('L', (100, 100), 'white').save(pattern % page, dpi=(300, 300))
            self.assertEqual(list(self.consume.iterdir()), [])
            return subprocess.CompletedProcess(command, status)

        with patch.object(scanner.subprocess, 'run', side_effect=scanimage):
            return scanner.scan(self.spool, self.consume, 'brother5:net1;dev0')

    def test_complete_stack_becomes_one_pdf(self):
        self.assertTrue(self.run_scan(2, 7))
        documents = list(self.consume.glob('*.pdf'))
        self.assertEqual(len(documents), 1)
        self.assertTrue(documents[0].read_bytes().startswith(b'%PDF'))
        with pikepdf.open(documents[0]) as pdf:
            self.assertEqual(len(pdf.pages), 2)
        self.assertEqual(list(self.spool.glob('Brother-*')), [])

    def test_empty_feeder_submits_nothing(self):
        self.assertFalse(self.run_scan(0, 7))
        self.assertEqual(list(self.consume.iterdir()), [])

    def test_jam_retains_pages_without_submitting_partial_document(self):
        self.assertFalse(self.run_scan(1, 6))
        self.assertEqual(len(list(self.spool.glob('Brother-*/page-*.tiff'))), 1)
        self.assertEqual(list(self.consume.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
