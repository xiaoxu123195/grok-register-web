from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGES_DIR = ROOT / 'static/js/pages'


class ClipboardFallbackTest(unittest.TestCase):
    """Copy buttons must keep working on plain-HTTP server deployments.

    ``navigator.clipboard`` only exists in a secure context (HTTPS or
    localhost). Reached over ``http://<ip>:<port>`` it is ``undefined``, so a
    direct ``navigator.clipboard.writeText(...)`` throws inside the click
    handler and the button silently does nothing.
    """

    def test_pages_never_touch_the_clipboard_api_directly(self):
        for page in sorted(PAGES_DIR.glob('*.js')):
            source = page.read_text(encoding='utf-8')
            self.assertNotIn(
                'navigator.clipboard',
                source,
                msg=f'{page.name} must copy through static/js/clipboard.js',
            )

    def test_results_page_copies_through_the_shared_helper(self):
        source = (ROOT / 'static/js/pages/results.js').read_text(encoding='utf-8')

        self.assertIn("from '../clipboard.js'", source)
        # Row copy, SSO bulk copy, account bulk copy, chat-denied copy.
        self.assertEqual(source.count('copyTextWithToast('), 4)

    def test_helper_falls_back_to_exec_command_outside_secure_contexts(self):
        source = (ROOT / 'static/js/clipboard.js').read_text(encoding='utf-8')

        self.assertIn('window.isSecureContext', source)
        self.assertIn("document.execCommand('copy')", source)
        self.assertIn('export async function copyText(', source)
        self.assertIn('export async function copyTextWithToast(', source)


if __name__ == '__main__':
    unittest.main()
