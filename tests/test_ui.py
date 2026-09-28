import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest


class UITests(unittest.TestCase):
    def page(self):
        return AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'delivery_app.py')).run(timeout=30)

    def test_default_step_and_reset(self):
        at = self.page()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['sim'].now, 0)
        at.button(key='step').click().run()
        self.assertEqual(at.session_state['sim'].now, 5)
        at.button(key='reset').click().run()
        self.assertEqual(at.session_state['sim'].now, 0)
        self.assertFalse(at.exception)

    def test_edits_do_not_change_existing_run(self):
        at = self.page()
        at.selectbox(key='strategy').select('G0').run()
        self.assertEqual(at.session_state['sim'].strategy, 'G2')
        self.assertTrue(at.button(key='step').disabled)
        at.button(key='reset').click().run()
        self.assertEqual(at.session_state['sim'].strategy, 'G0')

    def test_manual_event_and_comparison(self):
        at = self.page()
        next(b for b in at.button if b.label == '新增急救').click().run()
        self.assertIn('MAN001', at.session_state['sim'].tasks)
        self.assertEqual(at.session_state['sim'].queue[0], 'MAN001')
        at.button(key='compare').click().run(timeout=30)
        self.assertEqual(len(at.session_state['comparison']), 3)
        self.assertFalse(at.exception)

    def test_play_pause_and_predefined_event(self):
        at = self.page()
        at.button(key='start').click().run()
        self.assertTrue(at.session_state['running'])
        at.button(key='pause').click().run()
        self.assertFalse(at.session_state['running'])
        at.button(key='jump').click().run()
        at.button(key='jump').click().run()
        self.assertIn('EM01', at.session_state['sim'].tasks)
        self.assertFalse(at.exception)

