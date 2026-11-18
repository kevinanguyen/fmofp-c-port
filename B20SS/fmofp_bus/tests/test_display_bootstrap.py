"""The display programs make the folder FMOFP's logger writes into before the frozen logger looks for it.

The frozen `SysLogger.ensure_logs_directory` asks whether the folder is there and then makes it. Six display
programs started together on a fresh clone (git ignores `FMOFP/logs`, so a clone has none) all saw "not there";
one made it and the others died with FileExistsError before the bus started. `py -m fmofp_demo` failed that way
on its first start in four fresh checkouts of four (2026-11-17), and worked from the second start on.
`fmofp_display.app.bootstrap` makes the folder first, with `exist_ok`, so the frozen test finds it.
"""

import importlib.util
import os
import shutil
import tempfile
import unittest
from unittest import mock


@unittest.skipUnless(importlib.util.find_spec("PyQt6"), "PyQt6 is needed to import the display programs")
class LogsFolderTest(unittest.TestCase):
    def setUp(self):
        from fmofp_display import app
        self.cwd = os.getcwd()
        app.bootstrap()
        from FMOFP.Utils.common import fetching
        from FMOFP.Utils.logger.sys_logger import SysLogger
        self.app, self.fetching, self.frozen = app, fetching, SysLogger.ensure_logs_directory
        self.root = tempfile.mkdtemp(prefix="fmofp_data_")
        self.logs = os.path.join(self.root, "logs")
        self.saved = os.environ.get("FMOFP_DATA_DIR")
        os.environ["FMOFP_DATA_DIR"] = self.root  # a fresh clone's state: a data root with no logs folder in it
        fetching.reset_data_root()

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("FMOFP_DATA_DIR", None)
        else:
            os.environ["FMOFP_DATA_DIR"] = self.saved
        self.fetching.reset_data_root()
        os.chdir(self.cwd)
        shutil.rmtree(self.root, ignore_errors=True)

    def test_the_frozen_logger_dies_when_another_program_makes_the_folder_first(self):
        """The race, replayed in one process: the folder appears between the frozen test and its makedirs."""
        really_exists = os.path.exists

        def another_program_gets_there_first(path):
            found = really_exists(path)
            if path == self.logs and not found:
                os.mkdir(self.logs)
            return found

        with mock.patch("os.path.exists", side_effect=another_program_gets_there_first):
            with self.assertRaises(FileExistsError):
                self.frozen(None)

    def test_bootstrap_makes_the_folder_so_the_frozen_logger_finds_it(self):
        self.assertFalse(os.path.exists(self.logs))
        self.app.bootstrap()
        self.assertTrue(os.path.isdir(self.logs))
        with mock.patch("os.makedirs", side_effect=AssertionError("the frozen logger should find the folder")):
            self.assertEqual(self.logs, self.frozen(None))

    def test_a_second_program_does_not_mind_finding_the_folder(self):
        self.assertEqual(self.logs, self.app.ensure_fmofp_logs_dir())
        self.assertEqual(self.logs, self.app.ensure_fmofp_logs_dir())
        self.assertTrue(os.path.isdir(self.logs))


if __name__ == "__main__":
    unittest.main()
