"""Subprocess and HTTP regressions for the public credential wrapper."""
import base64
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent / 'fixtures'))
from atlassian_fake_server import fake_server

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/atlassian-onprem-safe/scripts/atlassian.py'
spec = importlib.util.spec_from_file_location('atlassian_client', SCRIPT)
client_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client_module)
TOKEN = "synthetic-PAT-/+AbC=quote'"
OTHER_TOKEN = 'other-product-secret'


class AtlassianTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = fake_server()
        cls.base, cls.calls, cls.responses = cls.server.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = {f'{p.upper()}_BASE_URL': self.base + '/' + p for p in client_module.PRODUCTS}
        self.config.update({f'{p.upper()}_TOKEN': TOKEN for p in client_module.PRODUCTS})
        self.config['CONFLUENCE_TOKEN'] = OTHER_TOKEN
        self.file = self.directory / 'tokens.env'
        self.save()
        self.calls.clear()
        self.responses.clear()
        self.env = {**os.environ, 'ATLASSIAN_CONFIG_DIR': str(self.directory), 'ATLASSIAN_PROFILE': '',
                    'PYTHONDONTWRITEBYTECODE': '1'}

    def save(self):
        client_module.write_private(self.file, self.config)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def success(self, *args):
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def body_file(self, body):
        file = self.directory / 'request with spaces.json'
        file.write_text(json.dumps(body), encoding='utf-8')
        return str(file)

    def test_bearer_context_and_query_encoding(self):
        self.success('jira', 'search', 'project = DEMO AND text ~ "hello world"', '--query', 'fields=summary,status')
        call = self.calls[0]
        self.assertEqual(call['authorization'], 'Bearer ' + TOKEN)
        self.assertEqual(call['path'], '/jira/rest/api/2/search')
        self.assertEqual(call['query']['jql'], ['project = DEMO AND text ~ "hello world"'])
        self.assertEqual(call['query']['fields'], ['summary,status'])

    def test_basic_selected_explicitly(self):
        self.config['JIRA_USERNAME'] = 'reader'
        self.save()
        self.success('jira', 'issue', 'DEMO-1')
        self.assertEqual(self.calls[0]['authorization'], 'Basic ' + base64.b64encode(f'reader:{TOKEN}'.encode()).decode())

    def test_private_file_round_trip_and_no_execution(self):
        parsed = client_module.parse_config(self.file.read_text(), client_module.Redactor())
        self.assertEqual(parsed['JIRA_TOKEN'], TOKEN)
        evil = "$(touch should-not-exist)`echo no`"
        parsed = client_module.parse_config("JIRA_TOKEN='" + evil + "'\n", client_module.Redactor())
        self.assertEqual(parsed['JIRA_TOKEN'], evil)
        if os.name != 'nt':
            self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)

    def test_missing_config(self):
        self.file.unlink()
        result = self.cli('jira', 'issue', 'DEMO-1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('setup-tokens', result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(self.calls, [])

    def test_missing_product_and_bad_config_do_not_echo_values(self):
        self.config['JIRA_TOKEN'] = ''
        self.save()
        result = self.cli('jira', 'issue', 'DEMO-1')
        self.assertIn('JIRA_TOKEN', result.stderr)
        self.file.write_text("JIRA_TOKEN='unterminated-secret\n")
        result = self.cli('jira', 'issue', 'DEMO-1')
        self.assertNotIn('unterminated-secret', result.stderr)
        self.assertNotEqual(result.returncode, 0)

    @unittest.skipIf(os.name == 'nt', 'POSIX mode check')
    def test_loose_permissions_refused(self):
        self.file.chmod(0o644)
        result = self.cli('jira', 'issue', 'DEMO-1')
        self.assertIn('chmod 600', result.stderr)
        self.assertEqual(self.calls, [])

    def test_named_profile_and_invalid_profile(self):
        self.file.rename(self.directory / 'tokens.prod.env')
        self.env['ATLASSIAN_PROFILE'] = 'prod'
        self.success('jira', 'issue', 'DEMO-1')
        self.env['ATLASSIAN_PROFILE'] = '../../other'
        self.assertNotEqual(self.cli('jira', 'issue', 'DEMO-1').returncode, 0)

    def test_pagination_all_products(self):
        for product, args, key in [('bitbucket', ['projects'], 'values'), ('jira', ['search', 'project=DEMO'], 'issues'),
                                   ('confluence', ['search', 'type=page'], 'results')]:
            with self.subTest(product=product):
                self.calls.clear()
                data = self.success(product, *args, '--all')
                self.assertTrue(data['complete'])
                self.assertEqual(data['pageCount'], 2)
                self.assertEqual(len(self.calls), 2)
                self.assertEqual(sum(len(page[key]) for page in data['pages']), 2)
                self.assertTrue(all(c['path'].startswith('/' + product + '/rest/api/') for c in self.calls))
        self.calls.clear()
        self.success('bitbucket', 'projects', '--all')
        self.assertEqual(self.calls[1]['query']['start'], ['7'])

    def test_single_page_and_bounded_pagination(self):
        self.assertIn('isLastPage', self.success('bitbucket', 'projects'))
        self.assertEqual(len(self.calls), 1)
        data = self.success('bitbucket', 'projects', '--all', '--max-pages', '1')
        self.assertFalse(data['complete'])
        self.assertIn('start=7', data['next'])
        self.assertNotEqual(self.cli('bitbucket', 'projects', '--max-pages', '101').returncode, 0)

    def test_jira_comments_pagination(self):
        def response(handler):
            start = 1 if 'startAt=1' in handler.path else 0
            return 200, {'comments': [{'id': start}], 'startAt': start, 'maxResults': 1, 'total': 2}, {}
        self.responses['/jira/rest/api/2/issue/DEMO-1/comment'] = response
        data = self.success('jira', 'comments', 'DEMO-1', '--all')
        self.assertEqual(data['pageCount'], 2)

    def test_confluence_offset_fallback(self):
        def response(handler):
            start = 1 if 'start=1' in handler.path else 0
            return 200, {'results': [] if start else [{'id': '1'}], 'start': start, 'size': 0 if start else 1, 'limit': 1}, {}
        self.responses['/confluence/rest/api/space'] = response
        self.assertEqual(self.success('confluence', 'GET', '/rest/api/space', '--all')['pageCount'], 2)

    def test_next_query_links_and_repeat_detection(self):
        path = '/confluence/rest/api/content/search'
        self.responses[path] = (200, {'results': [], '_links': {'next': '?start=1'}}, {})
        result = self.cli('confluence', 'search', 'type=page', '--all')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('repeated', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_foreign_next_link_never_receives_credentials(self):
        self.responses['/confluence/rest/api/content/search'] = (200, {'_links': {'next': 'https://evil.example/rest/api/content'}}, {})
        result = self.cli('confluence', 'search', 'type=page', '--all')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls), 1)

    def test_unsafe_paths_and_cross_product_calls_refused(self):
        for path in ['https://evil.example/rest/api/2/myself', '//evil.example/rest/api/2/myself',
                     '/rest/api/2/../../other', '/rest/api/2/%252e%252e/other',
                     '/rest/api/2/a%5c..%5cother', '/rest/api/2/a#fragment',
                     self.base + '/confluence/rest/api/user/current', '/rest/api/2/a%00b']:
            with self.subTest(path=path):
                self.assertNotEqual(self.cli('jira', 'GET', path).returncode, 0)
        self.assertEqual(self.calls, [])

    def test_redirect_is_not_followed_even_to_same_origin(self):
        self.responses['/jira/rest/api/2/myself'] = (302, '', {'Location': self.base + '/jira/rest/api/2/redirected'})
        result = self.cli('jira', 'GET', '/rest/api/2/myself')
        self.assertIn('HTTP 302', result.stderr)
        self.assertEqual(len(self.calls), 1)

    def test_success_redaction_in_keys_values_and_basic(self):
        self.config['JIRA_USERNAME'] = 'reader'
        self.save()
        basic = base64.b64encode(f'reader:{TOKEN}'.encode()).decode()
        self.responses['/jira/rest/api/2/myself'] = (200, {'note': TOKEN + ' ' + OTHER_TOKEN + ' ' + basic,
                                                         TOKEN: 'key also scrubbed', 'password': 'unknown-secret'}, {})
        result = self.cli('jira', 'GET', '/rest/api/2/myself')
        self.assertEqual(result.returncode, 0, result.stderr)
        for value in [TOKEN, OTHER_TOKEN, basic, 'unknown-secret']:
            self.assertNotIn(value, result.stdout + result.stderr)
        self.assertIn('[redacted]', result.stdout)

    def test_error_redaction_json_and_plaintext(self):
        for body in [{'message': TOKEN + ' ' + OTHER_TOKEN}, TOKEN + ' ' + OTHER_TOKEN]:
            self.responses['/jira/rest/api/2/myself'] = (401, body, {})
            result = self.cli('jira', 'GET', '/rest/api/2/myself')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertIn('HTTP 401', result.stderr)
            self.assertNotIn(TOKEN, result.stderr)
            self.assertNotIn(OTHER_TOKEN, result.stderr)

    def test_error_body_secret_fields_are_redacted(self):
        body = {"errors": [{"message": "denied", "password": "unknown-error-secret"}],
                "apiKey": "unknown-api-key", "detail": {"session_token": "unknown-session"}}
        self.responses["/jira/rest/api/2/myself"] = (403, body, {})
        result = self.cli("jira", "GET", "/rest/api/2/myself")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTP 403", result.stderr)
        self.assertIn("denied", result.stderr)
        for value in ["unknown-error-secret", "unknown-api-key", "unknown-session"]:
            self.assertNotIn(value, result.stderr)
        self.assertIn("[redacted]", result.stderr)

    def test_numeric_password_redaction_preserves_json(self):
        self.config['JIRA_TOKEN'] = '12345'
        self.save()
        self.responses['/jira/rest/api/2/myself'] = (200, {'value': 12345, 'safe': 42}, {})
        result = self.cli('jira', 'GET', '/rest/api/2/myself')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'value': '[redacted]', 'safe': 42})
        self.assertNotIn('12345', result.stdout)

    def test_oversized_error_body_is_omitted(self):
        self.responses['/jira/rest/api/2/myself'] = (500, 'x' * (client_module.MAX_BODY - 3) + TOKEN, {})
        result = self.cli('jira', 'GET', '/rest/api/2/myself')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('body omitted', result.stderr)
        self.assertNotIn(TOKEN[:3], result.stderr)
        self.assertLess(len(result.stderr), 200)

    def test_short_password_is_redacted(self):
        self.config['JIRA_TOKEN'] = 'aB!'
        self.save()
        self.responses['/jira/rest/api/2/myself'] = (500, 'failure aB!', {})
        result = self.cli('jira', 'GET', '/rest/api/2/myself')
        self.assertNotIn('aB!', result.stderr)

    def test_preview_and_both_confirmation_flags_required(self):
        file = self.body_file({'body': 'Synthetic approved text'})
        for flags in [[], ['--write'], ['--confirmed']]:
            result = self.cli('jira', 'comment', 'DEMO-1', '--body-file', file, *flags)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Request summary:', result.stderr)
            self.assertIn('Write refused', result.stderr)
            self.assertEqual(result.stdout, '')
        self.assertEqual(self.calls, [])

    def test_four_supported_writes(self):
        cases = [('bitbucket', ['pr-comment', 'DEMO', 'repo', '7'], {'text': 'hello'}, 'POST', '/comments'),
                 ('jira', ['comment', 'DEMO-1'], {'body': 'hello'}, 'POST', '/comment'),
                 ('jira', ['transition', 'DEMO-1'], {'transition': {'id': '31'}}, 'POST', '/transitions'),
                 ('confluence', ['update-page', '123'], {'type': 'page', 'title': 'Demo', 'version': {'number': 5},
                                                       'body': {'storage': {'value': '<p>hello</p>', 'representation': 'storage'}}}, 'PUT', '/content/123')]
        for product, args, body, method, suffix in cases:
            with self.subTest(product=product, args=args):
                result = self.cli(product, *args, '--body-file', self.body_file(body), '--write', '--confirmed')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Request summary:', result.stderr)
                self.assertEqual(self.calls[-1]['method'], method)
                self.assertEqual(self.calls[-1]['body'], body)
                self.assertTrue(self.calls[-1]['path'].endswith(suffix))
                json.loads(result.stdout)

    def test_write_summary_redacted_and_extra_fields_rejected(self):
        file = self.body_file({'body': 'hello ' + TOKEN})
        result = self.cli('jira', 'comment', 'DEMO-1', '--body-file', file)
        self.assertNotIn(TOKEN, result.stderr)
        file = self.body_file({'body': 'hello', 'visibility': {'type': 'role', 'value': 'admin'}})
        result = self.cli('jira', 'comment', 'DEMO-1', '--body-file', file, '--write', '--confirmed')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls, [])

    def test_generic_writes_and_identifier_injection_refused(self):
        for args in [('jira', 'POST', '/rest/api/2/issue'), ('jira', 'issue', 'DEMO-1/comment'),
                     ('jira', 'GET', '/rest/api/2/myself', '--write', '--confirmed'),
                     ('jira', 'comment', 'DEMO-1', '--write', '--confirmed')]:
            self.assertNotEqual(self.cli(*args).returncode, 0)
        self.assertEqual(self.calls, [])

    def test_verify_endpoints_all_products(self):
        expected = {'bitbucket': ['/bitbucket/rest/api/1.0/application-properties'],
                    'jira': ['/jira/rest/api/2/serverInfo', '/jira/rest/api/2/myself'],
                    'confluence': ['/confluence/rest/api/user/current']}
        for product, paths in expected.items():
            self.calls.clear()
            self.success(product, 'verify')
            self.assertEqual([c['path'] for c in self.calls], paths)

    def test_bitbucket_common_routes_and_comment_path(self):
        for args, suffix in [(['repos', 'DEMO'], '/projects/DEMO/repos'),
                             (['prs', 'DEMO', 'repo'], '/projects/DEMO/repos/repo/pull-requests'),
                             (['pr', 'DEMO', 'repo', '7'], '/pull-requests/7'),
                             (['activities', 'DEMO', 'repo', '7'], '/pull-requests/7/activities')]:
            self.success('bitbucket', *args)
            self.assertTrue(self.calls[-1]['path'].endswith(suffix))
        self.calls.clear()
        result = self.cli('bitbucket', 'comments', 'DEMO', 'repo', '7')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls, [])
        self.success('bitbucket', 'comments', 'DEMO', 'repo', '7', '--query', 'path=src/main.ts')
        self.assertEqual(self.calls[-1]['query']['path'], ['src/main.ts'])

    def test_diff_and_page_view(self):
        data = self.success('bitbucket', 'diff', 'DEMO', 'repo', '7')
        self.assertTrue(data['diff'].startswith('diff --git'))
        self.success('confluence', 'page', '123', '--query', 'expand=body.view,version')
        self.assertEqual(self.calls[-1]['query']['expand'], ['body.view,version'])

    def test_cloud_and_remote_http_refused(self):
        for base in ['https://tenant.atlassian.net', 'https://api.bitbucket.org', 'http://intranet.example/jira',
                     'https://user:password@example.com/jira', 'https://example.com/jira?x=1']:
            self.config['JIRA_BASE_URL'] = base
            self.save()
            self.assertNotEqual(self.cli('jira', 'issue', 'DEMO-1').returncode, 0)
        self.assertEqual(self.calls, [])

    def test_tls_defaults_ca_and_explicit_warning(self):
        with patch.object(client_module.ssl, 'create_default_context', wraps=ssl.create_default_context) as trusted:
            client_module.Client('jira', self.config)
            trusted.assert_called_once_with(cafile=None)
        self.config['JIRA_CA_BUNDLE'] = '/synthetic/company-ca.pem'
        with patch.object(client_module.ssl, 'create_default_context', return_value=ssl.create_default_context()) as trusted:
            client_module.Client('jira', self.config)
            trusted.assert_called_once_with(cafile='/synthetic/company-ca.pem')
        self.config.pop('JIRA_CA_BUNDLE')
        self.config['JIRA_INSECURE_TLS'] = '1'
        self.save()
        result = self.cli('jira', 'issue', 'DEMO-1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('verification DISABLED', result.stderr)

    def test_setup_refuses_piped_credentials(self):
        result = self.cli('setup')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('interactive terminal', result.stderr)

    def test_setup_private_file_windows_acl_precedes_content(self):
        # Exercise the Windows branch with mocked commands; actual Windows CI also checks it.
        windows_file = self.directory / 'windows.env'
        events = []
        def run_command(args, **kwargs):
            events.append(args[0])
            if args[0] == 'icacls':
                self.assertEqual(Path(args[1]).read_bytes(), b'')
                self.assertIn('/inheritance:r', args)
                self.assertIn('*S-1-5-21-123:F', args)
            return subprocess.CompletedProcess(args, 0, stdout='"user","S-1-5-21-123"\n')
        windows_os = Mock(wraps=os)
        windows_os.name = 'nt'
        with patch.object(client_module, 'os', windows_os), patch.object(client_module.subprocess, 'run', side_effect=run_command):
            client_module.write_private(windows_file, self.config)
        self.assertEqual(events, ['whoami', 'icacls'])
        self.assertIn('JIRA_TOKEN=', windows_file.read_text())

    def test_interactive_setup_hides_credentials_and_checks_jira(self):
        self.file.unlink()
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        output = Terminal()
        answers = ['', self.base + '/jira', '', '', '0', '']
        with patch.dict(os.environ, self.env), patch.object(sys.stdin, 'isatty', return_value=True), redirect_stdout(output), patch('builtins.input', side_effect=answers), patch.object(client_module.getpass, 'getpass', return_value=TOKEN) as hidden:
            client_module.setup(client_module.Redactor())
        hidden.assert_called_once()
        self.assertNotIn(TOKEN, output.getvalue())
        self.assertIn('check passed', output.getvalue())
        self.assertEqual([c['path'] for c in self.calls], ['/jira/rest/api/2/serverInfo', '/jira/rest/api/2/myself'])
        self.assertTrue(self.file.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell launcher')
    def test_powershell_launcher(self):
        launcher = SCRIPT.with_name('atlassian.ps1')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-File', str(launcher), 'jira', 'issue', 'DEMO-1'],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'ok': True})


if __name__ == '__main__':
    unittest.main()
