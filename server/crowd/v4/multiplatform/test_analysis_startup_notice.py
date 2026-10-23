"""Only the exact observed CLI startup notice may pass the tool-event gate."""
import json
from test_analysis import JobsTests, FAKE_PROVIDER
import sys

NOTICE = 'Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.'

class StartupNoticeTests(JobsTests):
    def provider_notice(self, message, event='item.completed'):
        prefix = "print(" + repr(json.dumps({'type': event, 'item': {'type': 'error', 'message': message}})) + ")\n"
        source = FAKE_PROVIDER.replace("kind = 'command_execution'", prefix + "kind = 'command_execution'")
        self.executable.write_text('#!' + sys.executable + '\n' + source)

    def test_exact_startup_notice_succeeds_without_enabling_tools(self):
        self.provider_notice(NOTICE)
        self.wait(self.start(), 'completed')
        command = self.manager.command(self.base)
        self.assertIn('suppress_unstable_features_warning=true', command)
        self.assertIn('code_mode_host', command)

    def test_other_errors_or_event_forms_are_rejected(self):
        for message, event in [('Provider unauthorized', 'item.completed'), (NOTICE + ' extra', 'item.completed'), (NOTICE, 'item.started')]:
            with self.subTest(message=message, event=event):
                self.provider_notice(message, event)
                result = self.wait(self.start(), 'failed')
                self.assertEqual(result['error'], 'analysis_unexpected_tool_event')
