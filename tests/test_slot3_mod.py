import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import contextlib
import io
spec = importlib.util.spec_from_file_location('mod', Path(__file__).parents[1] / 'tools/slot3_mod.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class ModTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'saves'
        self.backups = Path(self.tmp.name) / 'backups'
        for slot in ['', 'default2', 'default3']:
            p = self.root / slot
            p.mkdir(parents=True, exist_ok=True)
            (p / 'sasquatch.stuff').write_text(json.dumps({'VERSION': 2, 'coins': 690, 'bankcoin': 5, 'progress': {'mission': 'keep', 'cars': [1,2]}}))
        self.f = self.root / 'default3/sasquatch.stuff'
        self.original = self.f.read_bytes()
        (self.root / 'default3/other.stuff').write_bytes(b'unchanged')
    def apply(self, **kw):
        return m.apply(self.root, self.backups, check_closed=lambda: None, **kw)
    def test_roundtrip_only_slot3(self):
        before = {p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        backup = self.apply(coins=2_000_000)
        for p,data in before.items():
            if p != self.f:
                self.assertEqual(p.read_bytes(),data)
        d=json.loads(self.f.read_bytes()); self.assertEqual(d['coins'],2_000_000)
        self.assertEqual(d['progress'],json.loads(self.original)['progress'])
        self.assertEqual((backup/'default3/other.stuff').read_bytes(),b'unchanged')
        m.undo(self.root,backup,check_closed=lambda:None)
        self.assertEqual(self.f.read_bytes(),self.original)
    def test_refuses_running_game_before_backup(self):
        def running(): raise m.ModError('running')
        with self.assertRaises(m.ModError): m.apply(self.root,self.backups,coins=10,check_closed=running)
        self.assertEqual(self.f.read_bytes(),self.original)
        self.assertFalse(self.backups.exists())
    def test_overflow_negative_and_unknown_format(self):
        for n in [-2_000_000_001, 2_000_000_000, 2_147_483_648]:
            with self.assertRaises(m.ModError): self.apply(coins=n)
        self.apply(coins=-2)
        self.assertEqual(json.loads(self.f.read_text())['coins'], -2)
        self.f.write_text('{"VERSION":99,"coins":3}')
        with self.assertRaises(m.ModError): self.apply(coins=10)
    def test_restore_refuses_new_progress(self):
        backup=self.apply(coins=100)
        self.f.write_text('{"VERSION":2,"coins":90,"progress":"new"}')
        with self.assertRaises(m.ModError):m.undo(self.root,backup,check_closed=lambda:None)
        self.assertEqual(json.loads(self.f.read_text())['progress'],'new')
    def test_noop_and_bank(self):
        self.assertIsNone(self.apply(coins=690))
        self.apply(bank=2000000)
        self.assertEqual(json.loads(self.f.read_text())['bankcoin'],2000000)
    def test_symlink_rejected(self):
        target=self.root/'sasquatch.stuff'; self.f.unlink();self.f.symlink_to(target)
        with self.assertRaises(m.ModError):self.apply(coins=10)
    def test_race_rejected(self):
        self.f.write_bytes(self.original+b' ')
        with self.assertRaises(m.ModError):m.atomic_replace(self.f,self.original,b'wrong')
    def test_duplicate_keys(self):
        self.f.write_text('{"VERSION":2,"coins":5,"coins":6}')
        with self.assertRaises(m.ModError):self.apply(coins=10)

    def test_combined_menu_input(self):
        output = io.StringIO()
        with patch.object(m, 'ROOT', self.root), patch.object(m, 'PACKAGE', Path(self.tmp.name)), patch.object(m, 'require_closed'), patch.object(m.apply, '__defaults__', (None, None, lambda: None)), patch('builtins.input', side_effect=['1 4444']), contextlib.redirect_stdout(output):
            m.interactive()
        self.assertEqual(json.loads(self.f.read_text())['coins'], 4444)
        self.assertIn('is now 4444', output.getvalue())
    def test_invalid_input_retries_instead_of_exiting(self):
        with patch.object(m, 'ROOT', self.root), patch.object(m, 'PACKAGE', Path(self.tmp.name)), patch.object(m, 'require_closed'), patch.object(m.apply, '__defaults__', (None, None, lambda: None)), patch('builtins.input', side_effect=['wrong', '1 abc', '1', '4444']), contextlib.redirect_stdout(io.StringIO()):
            m.interactive()
        self.assertEqual(json.loads(self.f.read_text())['coins'], 4444)

    def test_new_save_missing_coins_read_edit_and_undo(self):
        fresh = {'VERSION': 2, 'current_map': 'tutorial-exit', 'map_locations': {}, 'progress': {'keep': True}}
        self.f.write_text(json.dumps(fresh))
        original = self.f.read_bytes()
        _, _, read = m.read_save(self.root)
        self.assertNotIn('coins', read)
        self.assertEqual(self.f.read_bytes(), original)
        backup = self.apply(coins=4444)
        self.assertEqual(json.loads(self.f.read_text())['coins'], 4444)
        self.assertEqual(json.loads(self.f.read_text())['progress'], fresh['progress'])
        m.undo(self.root, backup, check_closed=lambda: None)
        self.assertEqual(self.f.read_bytes(), original)
    def test_invalid_wallet_types_and_unrecognized_empty_save(self):
        for value in [None, True, '10', 1.5]:
            self.f.write_text(json.dumps({'VERSION': 2, 'coins': value}))
            with self.assertRaises(m.ModError): m.read_save(self.root)
        self.f.write_text('{"VERSION":2}')
        with self.assertRaises(m.ModError): m.read_save(self.root)

if __name__=='__main__': unittest.main()
