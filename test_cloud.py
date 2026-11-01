import contextlib
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as Args
import unittest
from unittest.mock import patch, mock_open

spec = importlib.util.spec_from_loader('cloud', SourceFileLoader('cloud', str(Path(__file__).with_name('cloud'))))
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class CloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.src = self.base/'remote'
        self.dst = self.base/'local'
        self.src.mkdir()
        self.env = patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.base/'config')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()
        self.addCleanup(self.silence.__exit__, None, None, None)
        c.QUIET = False

    def init(self, full=False):
        c.cmd_init(Args(remote=str(self.src), local=str(self.dst), full_index=full))

    def pin(self, rel):
        with c.locked():
            c.cmd_pin(Args(paths=[str(self.dst/rel)]))

    def unpin(self, rel):
        with c.locked():
            c.cmd_unpin(Args(paths=[str(self.dst/rel)]))

    def test_init_does_not_walk_remote(self):
        (self.src/'ignored').mkdir()
        (self.src/'ignored'/'large.bin').write_bytes(b'x')
        with patch.object(c, '_scan', side_effect=AssertionError('recursive scan during lazy init')):
            self.init()
        self.assertTrue(c.cfg['lazy'])
        self.assertEqual(c.state['files'], {})
        self.assertFalse((self.dst/'ignored').exists())
        self.assertIn(str(self.dst), c.profiles())

    def test_only_selected_folder_scanned_and_synced(self):
        for d in ['selected', 'untouched']:
            (self.src/d).mkdir()
            (self.src/d/'a.txt').write_text(d)
        self.init()
        original = c._scan
        calls = []
        def guarded(path, stubs):
            calls.append(str(path))
            self.assertNotEqual(str(path), str(self.src))
            self.assertNotIn('untouched', str(path))
            return original(path, stubs)
        with patch.object(c, '_scan', side_effect=guarded):
            self.pin('selected')
            c.sync()
        self.assertTrue(calls)
        self.assertEqual((self.dst/'selected'/'a.txt').read_text(), 'selected')
        self.assertFalse((self.dst/'untouched').exists())

    def test_unpin_uploads_then_does_not_redownload_or_delete_remote(self):
        (self.src/'a.txt').write_text('before')
        self.init()
        self.pin('a.txt')
        (self.dst/'a.txt').write_text('changed content')
        self.unpin('a.txt')
        self.assertEqual((self.src/'a.txt').read_text(), 'changed content')
        self.assertFalse((self.dst/'a.txt').exists())
        self.assertTrue((self.dst/'a.txt.cloud').exists())
        c.sync()
        self.assertFalse((self.dst/'a.txt').exists())
        self.assertTrue((self.src/'a.txt').exists())
        self.pin('a.txt')
        self.assertTrue((self.dst/'a.txt').exists())

    def test_sync_new_edits_deletes_in_pinned_folder(self):
        (self.src/'sub').mkdir()
        (self.src/'sub'/'a').write_text('one')
        self.init()
        self.pin('sub')
        (self.dst/'sub'/'new').write_text('new local file')
        (self.src/'sub'/'a').write_text('remote changed longer')
        c.sync()
        self.assertEqual((self.src/'sub'/'new').read_text(), 'new local file')
        self.assertEqual((self.dst/'sub'/'a').read_text(), 'remote changed longer')
        (self.dst/'sub'/'a').unlink()
        c.sync()
        self.assertFalse((self.src/'sub'/'a').exists())
        self.assertTrue(list((self.src/c.TRASH).rglob('a')))

    def test_disconnect_keeps_downloads_and_remote(self):
        (self.src/'a').write_text('keep me')
        (self.src/'b').write_text('online')
        self.init(full=True)
        self.pin('a')
        c.cmd_uninit(Args(yes=True))
        self.assertEqual((self.dst/'a').read_text(), 'keep me')
        self.assertEqual((self.src/'a').read_text(), 'keep me')
        self.assertFalse((self.dst/'b.cloud').exists())
        self.assertFalse((self.dst/c.CFG).exists())
        self.assertNotIn(str(self.dst), c.profiles())

    def test_legacy_index_and_empty_source(self):
        (self.src/'a').write_text('a')
        self.init(full=True)
        self.assertFalse(c.cfg['lazy'])
        self.assertTrue((self.dst/'a.cloud').exists())
        (self.src/'a').unlink()
        c.sync()
        self.assertFalse((self.dst/'a.cloud').exists())

    def test_unreadable_selection_aborts_before_deletion(self):
        (self.src/'a').write_text('keep')
        self.init()
        self.pin('a')
        original = os.lstat
        def denied(path, *args, **kwargs):
            if str(path) == str(self.src/'a'):
                raise PermissionError('unreadable remote file')
            return original(path, *args, **kwargs)
        with patch.object(os, 'lstat', side_effect=denied):
            with self.assertRaises(PermissionError):
                c.sync()
        self.assertTrue((self.dst/'a').exists())

    def test_migration_preserves_tracked_unpinned_file(self):
        (self.src/'a').write_text('a')
        self.init(full=True)
        (self.dst/'local-new').write_text('keep tracking')
        c.sync()
        c.cfg['lazy'] = True
        c.save_cfg()
        c.sync()
        self.assertEqual((self.dst/'local-new').read_text(), 'keep tracking')
        self.assertEqual((self.src/'local-new').read_text(), 'keep tracking')
        self.assertFalse((self.dst/'a').exists())

    def test_excluded_path_cannot_be_pinned(self):
        (self.src/'Library').mkdir()
        (self.src/'Library'/'a').write_text('ignored')
        self.init()
        with self.assertRaises(c.Stop):
            self.pin('Library')

    def test_nested_source_rejected(self):
        with self.assertRaises(c.Stop):
            c.cmd_init(Args(remote=str(self.src), local=str(self.src/'child'), full_index=False))

    def test_fstab_discovery_does_not_read_credentials(self):
        fixture = '# comment\n//example/nas /mnt/nas cifs credentials=/private/secret 0 0\n/dev/sda / ext4 defaults 0 0\n'
        with patch('builtins.open', mock_open(read_data=fixture)) as opened:
            entries = c.mount_sources()
            opened.assert_called_once_with('/etc/fstab')
        self.assertTrue(any(e['target'] == '/mnt/nas' for e in entries))
        self.assertTrue(all(set(e) == {'source', 'target', 'type'} for e in entries))

if __name__ == '__main__':
    unittest.main(verbosity=2)
