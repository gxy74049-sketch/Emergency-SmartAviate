import unittest
from unittest.mock import patch

import launcher


class LauncherTests(unittest.TestCase):
    def test_failed_install_stops_before_tests_and_app(self):
        with patch.object(launcher, 'action_install_deps', return_value=1), \
             patch.object(launcher, 'action_run_tests') as tests, \
             patch.object(launcher, 'action_run_app') as app:
            launcher.action_full_check()
        tests.assert_not_called()
        app.assert_not_called()

    def test_failed_tests_stop_before_app(self):
        with patch.object(launcher, 'action_install_deps', return_value=0), \
             patch.object(launcher, 'action_run_tests', return_value=1), \
             patch.object(launcher, 'action_run_app') as app:
            launcher.action_full_check()
        app.assert_not_called()

    def test_successful_checks_start_app(self):
        with patch.object(launcher, 'action_install_deps', return_value=0), \
             patch.object(launcher, 'action_run_tests', return_value=0), \
             patch.object(launcher, 'action_run_app') as app:
            launcher.action_full_check()
        app.assert_called_once_with()
