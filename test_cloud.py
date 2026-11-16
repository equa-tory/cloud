import contextlib
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import os
import plistlib
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
        self.base = Path(self.tmp.name).resolve()
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
        with patch.object(c.sys, 'platform', 'linux'), patch('builtins.open', mock_open(read_data=fixture)) as opened:
            entries = c.mount_sources()
            opened.assert_called_once_with('/etc/fstab')
        self.assertTrue(any(e['target'] == '/mnt/nas' for e in entries))
        self.assertTrue(all(set(e) == {'source', 'target', 'type'} for e in entries))

    def test_browsing_before_first_connection_uses_default_excludes(self):
        with patch.object(c, 'cfg', {}):
            self.assertFalse(c.bad('1_Projects'))
            self.assertTrue(c.bad('Library'))
            self.assertTrue(c.bad('.DS_Store'))
        with patch.object(c, 'cfg', {'exclude': []}):
            self.assertFalse(c.bad('Library'))

    def test_macos_discovers_finder_network_mounts(self):
        fixture = ('/dev/disk3s1 on / (apfs, local)\n'
                   '//equa@192.168.1.50/%40 on /Volumes/192.168.1.50 (smbfs, nodev, nosuid)\n'
                   'nas:/shared on /Volumes/Shared Files (nfs, nodev)\n')
        with patch.object(c.sys, 'platform', 'darwin'), \
                patch('builtins.open', side_effect=FileNotFoundError), \
                patch.object(c.subprocess, 'check_output', return_value=fixture):
            entries = c.mount_sources()
        self.assertEqual(entries, [
            {'source': '//equa@192.168.1.50/%40', 'target': '/Volumes/192.168.1.50', 'type': 'smbfs'},
            {'source': 'nas:/shared', 'target': '/Volumes/Shared Files', 'type': 'nfs'},
        ])

    def test_macos_mount_discovery_preserves_fstab_when_mount_fails(self):
        fixture = '//example/share /Volumes/share smbfs defaults 0 0\n'
        with patch.object(c.sys, 'platform', 'darwin'), \
                patch('builtins.open', mock_open(read_data=fixture)), \
                patch.object(c.subprocess, 'check_output', side_effect=OSError):
            self.assertEqual(c.mount_sources(), [
                {'source': '//example/share', 'target': '/Volumes/share', 'type': 'smbfs'}])

    def test_interval_saved_while_off_and_reused_after_toggle(self):
        self.init()
        with patch.object(c, 'sh', return_value=True), \
                patch.object(c, 'svc_files', return_value=[str(self.base/'sync.service'), str(self.base/'sync.timer')]), \
                patch.object(c.sys, 'platform', 'linux'):
            c.set_auto_interval(17)
            self.assertEqual(c.cfg['auto'], 0)
            c.load(str(self.dst))
            c.cmd_auto(Args(mode='on', seconds=None))
            self.assertEqual(c.cfg['auto'], 17)
            c.auto_off()
            c.load(str(self.dst))
            self.assertEqual(c.cfg['auto'], 0)
            self.assertEqual(c.cfg['auto_interval'], 17)
            c.cmd_auto(Args(mode='on', seconds=None))
            self.assertEqual(c.cfg['auto'], 17)

    def test_active_linux_interval_restarts_timer_with_new_seconds(self):
        self.init()
        service, timer = self.base/'sync.service', self.base/'sync.timer'
        with patch.object(c, 'sh', return_value=True) as sh, \
                patch.object(c, 'svc_files', return_value=[str(service), str(timer)]), \
                patch.object(c.sys, 'platform', 'linux'):
            c.auto_on(120)
            c.set_auto_interval(9)
        self.assertEqual(c.cfg['auto'], 9)
        self.assertIn('OnUnitActiveSec=9s', timer.read_text())
        self.assertIn('AccuracySec=1s', timer.read_text())
        self.assertEqual(sum(call.args == ('systemctl', '--user', 'restart', c.svc_name()+'.timer')
                             for call in sh.call_args_list), 2)

    def test_active_macos_interval_reloads_launch_agent(self):
        self.init()
        agent = self.base/'sync.plist'
        with patch.object(c, 'sh', return_value=True) as sh, \
                patch.object(c, 'svc_files', return_value=[str(agent)]), \
                patch.object(c.sys, 'platform', 'darwin'):
            c.auto_on(120)
            c.set_auto_interval(7)
        with agent.open('rb') as f:
            self.assertEqual(plistlib.load(f)['StartInterval'], 7)
        self.assertEqual(c.cfg['auto'], 7)
        self.assertEqual(sum(call.args[:2] == ('launchctl', 'bootstrap') for call in sh.call_args_list), 2)

    def test_invalid_interval_leaves_schedule_unchanged(self):
        self.init()
        c.cfg['auto'] = 120
        with patch.object(c, 'sh') as sh:
            for seconds in (0, -1):
                with self.assertRaises(c.Stop):
                    c.set_auto_interval(seconds)
                with self.assertRaises(c.Stop):
                    c.auto_on(seconds)
            sh.assert_not_called()
        self.assertEqual(c.cfg['auto'], 120)

    def test_auto_submenu_can_save_interval_without_enabling_sync(self):
        self.init()
        keys = iter([ord('j'), ord('j'), ord('j'), 10,
                     ord('j'), 10, '\x15', '5', '\n', 10,
                     ord('q'), ord('q'), ord('q')])
        class Screen:
            def keypad(self, value): pass
            def erase(self): pass
            def getmaxyx(self): return (24, 100)
            def addnstr(self, *args): pass
            def refresh(self): pass
            def timeout(self, value): pass
            def getch(self): return next(keys)
            def get_wch(self): return next(keys)
        class Thread:
            def __init__(self, target, **kw): self.target = target
            def start(self): self.target()
            def is_alive(self): return False
        curses = Args(curs_set=lambda value: None, wrapper=lambda app: app(Screen()),
                      A_BOLD=1, A_REVERSE=2, A_DIM=3, KEY_LEFT=260, KEY_DOWN=258,
                      KEY_UP=259, KEY_NPAGE=338, KEY_PPAGE=339, KEY_ENTER=343,
                      KEY_RIGHT=261, KEY_BACKSPACE=263, error=RuntimeError)
        with patch.dict('sys.modules', {'curses': curses}), \
                patch.object(c.sys.stdin, 'isatty', return_value=True), \
                patch.object(c.sys.stdout, 'isatty', return_value=True), \
                patch.object(c.threading, 'Thread', Thread):
            c.cmd_ui(Args(dir=str(self.dst)))
        c.load(str(self.dst))
        self.assertEqual(c.cfg['auto'], 0)
        self.assertEqual(c.cfg['auto_interval'], 5)

if __name__ == '__main__':
    unittest.main(verbosity=2)
