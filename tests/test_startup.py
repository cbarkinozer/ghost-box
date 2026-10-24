"""Regression check for macOS-hidden Qt plugin files."""

import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from main import prepare_qt_plugins


@unittest.skipUnless(sys.platform == "darwin", "macOS file flags only")
class StartupTests(unittest.TestCase):
    def test_hidden_flags_cleared_without_changing_other_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            platforms = root / "platforms"
            platforms.mkdir()
            plugin = platforms / "libqcocoa.dylib"
            plugin.touch()
            for path in (root, platforms, plugin):
                os.chflags(path, path.stat().st_flags | stat.UF_HIDDEN)
            expected = plugin.stat().st_flags & ~stat.UF_HIDDEN
            with patch("main.QLibraryInfo.path", return_value=str(root)):
                prepare_qt_plugins()
                prepare_qt_plugins()  # Repeated launches are safe.
            self.assertEqual(plugin.stat().st_flags, expected)
            for path in (root, platforms):
                self.assertFalse(path.stat().st_flags & stat.UF_HIDDEN)
