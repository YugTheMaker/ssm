import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).parents[1] / 'tools'))
import ss_console as console
import slot3_mod as saves

class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'saves'
        self.package = self.base / 'package'
        self.package.mkdir()
        for slot in (1, 2, 3):
            folder = saves.slot_path(self.root, slot)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'sasquatch.stuff').write_text(json.dumps({'VERSION':2, 'coins':slot*10, 'bankcoin':0, 'progress':{'keep':slot}}))
            (folder / 'inventory.stuff').write_text('unchanged')
    def run_session(self, slot, commands, checker=lambda:None):
        it = iter(commands)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            console.session(slot, root=self.root, package=self.package, read=lambda prompt:next(it), check_closed=checker)
        return output.getvalue()
    def snapshot(self):
        return {p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
    def test_amounts(self):
        for text,value in [('4444',4444),('2b',2000000000),('2 billion',2000000000),('two billion',2000000000),('1.5m',1500000),('2,000,000',2000000),('0',0),('-1',-1),('-2',-2),('- 1',-1),('-2b',-2000000000)]:
            self.assertEqual(console.parse_amount(text),value)
        for text in ['-2.1b','2.1b','0.5','2,00','float("inf")','1;echo hi','hello','nan','--1','-']:
            with self.assertRaises(saves.ModError):console.parse_amount(text)
    def test_each_slot_changes_only_its_currency_file(self):
        for slot in (1,2,3):
            before=self.snapshot()
            text=self.run_session(slot,['C = two billion','status','exit'])
            target=saves.slot_path(self.root,slot)/'sasquatch.stuff'
            after=self.snapshot()
            self.assertEqual([p for p in before if before[p]!=after[p]],[target])
            self.assertEqual(json.loads(target.read_text())['coins'],2000000000)
            self.assertIn('Saved and verified locally',text)
            self.assertIn('progress',json.loads(target.read_text()))
    def test_slot_one_backup_excludes_other_slots(self):
        self.run_session(1,['C=4444','exit'])
        backup=next((self.package/'console-backups').glob('*/default1'))
        self.assertFalse((backup/'default2').exists())
        self.assertFalse((backup/'default3').exists())
        self.assertTrue((backup/'inventory.stuff').exists())
    def test_undo_for_selected_slot(self):
        self.run_session(1,['C=4444','exit'])
        before=self.snapshot()
        self.run_session(3,['C=999','undo','exit'])
        self.assertEqual(before,self.snapshot())
    def test_running_game_blocks_and_session_survives(self):
        before=self.snapshot()
        def running():raise saves.ModError('Game running')
        text=self.run_session(3,['C=999','status','exit'],checker=running)
        self.assertEqual(before,self.snapshot())
        self.assertIn('Game running',text)
        self.assertFalse((self.package/'console-backups').exists())
    def test_unknown_command_never_executes(self):
        before=self.snapshot()
        text=self.run_session(3,['C = __import__("os")','S S 1','help','exit'])
        self.assertEqual(before,self.snapshot())
        self.assertIn('Stopped:',text)
    def test_invalid_slot(self):
        for slot in [0,4,True,'../']:
            with self.assertRaises(saves.ModError):saves.read_save(self.root,slot)

if __name__=='__main__':unittest.main()
