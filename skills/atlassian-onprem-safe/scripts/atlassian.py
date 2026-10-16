#!/usr/bin/env python3
"""Local credential boundary for Atlassian Server/DC. Python 3.10+, stdlib only."""
import argparse
import base64
import getpass
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import shlex
import ssl
import stat
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request

PRODUCTS = ('bitbucket', 'jira', 'confluence')
PREFIX = {'bitbucket': '/rest/api/1.0', 'jira': '/rest/api/2', 'confluence': '/rest/api'}
SUFFIXES = ('BASE_URL', 'TOKEN', 'USERNAME', 'CA_BUNDLE', 'INSECURE_TLS')
KEYS = {f'{p.upper()}_{s}' for p in PRODUCTS for s in SUFFIXES}
SENSITIVE = re.compile(r'token|password|passwd|secret|authorization|credential|api[_-]?key', re.I)
MAX_BODY = 16 * 1024 * 1024


class SafeError(Exception):
    pass


class Redactor:
    def __init__(self):
        self.values = set()

    def add(self, value):
        if value:
            # Include JSON/URL spellings and the Basic credential, even for short passwords.
            self.values.update((value, json.dumps(value, ensure_ascii=True)[1:-1],
                                quote(value, safe=''), quote(value, safe='').lower()))

    def text(self, value):
        for secret in sorted(self.values, key=len, reverse=True):
            value = value.replace(secret, '[redacted]')
        # Keep terminal control sequences out of model and terminal output.
        return ''.join(c if c in '\n\t' or ord(c) >= 32 and ord(c) != 127 else '?' for c in value)

    def clean(self, value):
        if isinstance(value, dict):
            return {self.text(k): '[redacted]' if SENSITIVE.search(k) else self.clean(v)
                    for k, v in value.items()}
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            return self.text(value)
        encoded = json.dumps(value)
        scrubbed = self.text(encoded)
        return scrubbed if encoded != scrubbed else value


def config_path():
    profile = os.environ.get('ATLASSIAN_PROFILE', '')
    if profile and not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', profile):
        raise SafeError('ATLASSIAN_PROFILE must contain only letters, digits, underscore or hyphen.')
    directory = Path(os.environ.get('ATLASSIAN_CONFIG_DIR', Path.home() / '.config/atlassian-onprem'))
    return directory / (f'tokens.{profile}.env' if profile else 'tokens.env')


def parse_config(text, redactor):
    config = {}
    for line in text.lstrip('\ufeff').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'\s*([A-Z_]+)\s*=(.*)', line)
        if not match or match[1] not in KEYS:
            raise SafeError('Invalid credentials file syntax or unknown key; run setup-tokens again.')
        try:
            parts = shlex.split(match[2], comments=False, posix=True)
        except ValueError:
            raise SafeError('Invalid quoting in credentials file; run setup-tokens again.') from None
        if len(parts) > 1:
            raise SafeError('Each credentials value must be quoted; run setup-tokens again.')
        value = parts[0] if parts else ''
        config[match[1]] = value
        if match[1].endswith('_TOKEN'):
            redactor.add(value)
    # Redact every configured product's token and Basic equivalent, even on another product's response.
    for product in PRODUCTS:
        user, token = (config.get(f'{product.upper()}_{s}', '') for s in ('USERNAME', 'TOKEN'))
        if user and token:
            redactor.add(base64.b64encode(f'{user}:{token}'.encode()).decode())
    return config


def load_config(redactor):
    file = config_path()
    try:
        if file.is_symlink():
            raise SafeError('Credentials file must not be a symlink.')
        if os.name != 'nt' and (file.stat().st_uid != os.getuid() or stat.S_IMODE(file.stat().st_mode) & 0o077):
            raise SafeError('Credentials must be owned by the current user with chmod 600; run setup-tokens.')
        return parse_config(file.read_text(encoding='utf-8'), redactor)
    except OSError:
        raise SafeError('Missing or unreadable credentials file. Ask the human to run setup-tokens in their terminal.') from None


def safe_path(path):
    decoded = path
    for _ in range(6):
        result = unquote(decoded)
        if result == decoded:
            break
        decoded = result
    else:
        raise SafeError('Refusing a multiply encoded API path.')
    if (any(c in decoded for c in '\\?#;') or '//' in decoded
            or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
            or any(s in ('.', '..') for s in decoded.split('/'))):
        raise SafeError('Refusing an unsafe API path.')
    return decoded


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, product, config):
        self.product = product
        root = product.upper()
        self.base = config.get(root + '_BASE_URL', '').rstrip('/')
        self.token = config.get(root + '_TOKEN', '')
        self.user = config.get(root + '_USERNAME', '')
        if not self.base or not self.token:
            raise SafeError(f'{root}_BASE_URL and {root}_TOKEN are required. Ask the human to run setup-tokens.')
        base = urlsplit(self.base)
        if (base.username or base.password or base.query or base.fragment or not base.hostname
                or base.scheme not in ('http', 'https')):
            raise SafeError('Base URL must be an HTTPS origin with an optional context path, without credentials or query.')
        if base.hostname.lower() == 'atlassian.net' or base.hostname.lower().endswith('.atlassian.net') or base.hostname.lower() == 'api.bitbucket.org':
            raise SafeError('Atlassian Cloud is out of scope; use the Cloud APIs or Atlassian Rovo MCP.')
        if base.scheme != 'https' and base.hostname not in ('127.0.0.1', '::1', 'localhost'):
            raise SafeError('HTTPS is required. Plain HTTP is allowed only on loopback for local tests.')
        safe_path(base.path)
        self.origin = (base.scheme, base.netloc)
        self.context = base.path
        self.api_root = base.path + PREFIX[product]
        insecure = config.get(root + '_INSECURE_TLS', '')
        if insecure not in ('', '0', '1'):
            raise SafeError(f'{root}_INSECURE_TLS must be 0 or 1.')
        if insecure == '1':
            print(f'WARNING: {root} TLS certificate and hostname verification DISABLED. Credentials can be intercepted.', file=sys.stderr)
            context = ssl._create_unverified_context()
        else:
            context = ssl.create_default_context(cafile=config.get(root + '_CA_BUNDLE') or None)
        # No environment proxy or redirect can silently forward the Authorization header.
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect())

    def url(self, path):
        parts = urlsplit(path)
        if parts.scheme or parts.netloc:
            if (parts.scheme, parts.netloc) != self.origin or parts.username or parts.password:
                raise SafeError('Refusing an API URL outside the configured server.')
            target = parts.path
        else:
            if path.startswith('//'):
                raise SafeError('Refusing a network-relative URL.')
            target = parts.path
            if target.startswith(PREFIX[self.product] + '/') or target == PREFIX[self.product]:
                target = self.context + target
            elif not target.startswith(self.api_root + '/') and target != self.api_root:
                raise SafeError('Use a product REST path starting with ' + PREFIX[self.product] + '/.')
        if parts.fragment:
            raise SafeError('API URLs must not have fragments.')
        decoded = safe_path(target)
        if not (decoded == self.api_root or decoded.startswith(self.api_root + '/')):
            raise SafeError('Refusing an API path outside the configured product REST root.')
        return urlunsplit((*self.origin, target, parts.query, ''))

    def request(self, path, method='GET', body=None):
        url = self.url(path)
        auth = 'Bearer ' + self.token
        if self.user:
            auth = 'Basic ' + base64.b64encode(f'{self.user}:{self.token}'.encode()).decode()
        headers = {'Authorization': auth, 'Accept': 'application/json'}
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/json; charset=utf-8'
            data = json.dumps(body).encode()
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    raise SafeError('Response exceeds the 16 MiB safety limit. Narrow the query.')
                text = raw.decode('utf-8', errors='replace')
        except HTTPError as exc:
            with exc:
                raw_error = exc.read(MAX_BODY + 1)
            # Never print a partial secret cut off by a response-size bound.
            text = 'Error body exceeds safety limit; body omitted.' if len(raw_error) > MAX_BODY else raw_error.decode('utf-8', errors='replace')
            raise SafeError(f'HTTP {exc.code}: {text}') from None
        except (URLError, TimeoutError, OSError, ValueError, HTTPException):
            suffix = ' The write outcome is uncertain; read the current state before retrying.' if method != 'GET' else ''
            raise SafeError('No complete response from the configured server. Check TLS, VPN, and server availability.' + suffix) from None
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except ValueError:
            if self.product == 'bitbucket' and urlsplit(url).path.endswith('.diff') and method == 'GET':
                return {'diff': text}
            raise SafeError('HTTP success without valid JSON (possibly an SSO login page). Ask the administrator about REST authentication.') from None


def with_query(path, values):
    p = urlsplit(path)
    if p.fragment:
        raise SafeError('API URLs must not have fragments.')
    query = dict(parse_qsl(p.query, keep_blank_values=True))
    query.update(values)
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), ''))


def next_page(client, path, data):
    if not isinstance(data, dict):
        return None
    if client.product == 'bitbucket' and 'isLastPage' in data:
        if data['isLastPage'] is True:
            return None
        cursor = data.get('nextPageStart')
        if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
            raise SafeError('Invalid Bitbucket pagination cursor.')
        return with_query(path, {'start': cursor})
    if client.product == 'jira' and all(k in data for k in ('startAt', 'maxResults', 'total')):
        start, size, total = (data[k] for k in ('startAt', 'maxResults', 'total'))
        if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in (start, size, total)):
            raise SafeError('Invalid Jira pagination metadata.')
        if start + size < total:
            if size == 0:
                raise SafeError('Jira returned a zero-sized page with results remaining.')
            return with_query(path, {'startAt': start + size})
    if client.product == 'confluence':
        link = data.get('_links', {}).get('next')
        if link:
            # Older Confluence returns /rest/api/... without its configured context.
            if link.startswith('?'):
                link = urlsplit(path).path + link
            return client.url(link)
        if '_links' not in data and all(k in data for k in ('results', 'start', 'limit', 'size')):
            start, limit, size = (data[k] for k in ('start', 'limit', 'size'))
            if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in (start, limit, size)):
                raise SafeError('Invalid Confluence pagination metadata.')
            if limit > 0 and size >= limit:
                return with_query(path, {'start': start + size})
    return None


def read_pages(client, path, all_pages, max_pages):
    pages, seen = [], set()
    while True:
        url = client.url(path)
        if url in seen:
            raise SafeError('Pagination repeated a URL; stopped without returning an incomplete result.')
        seen.add(url)
        data = client.request(url)
        if not all_pages:
            return data
        pages.append(data)
        following = next_page(client, url, data)
        if not following:
            return {'pages': pages, 'pageCount': len(pages), 'complete': True}
        if len(pages) >= max_pages:
            return {'pages': pages, 'pageCount': len(pages), 'complete': False, 'next': client.url(following)}
        path = following


def route(product, command, args):
    # Path identifiers cannot inject another route or query string.
    for arg in args:
        if command not in ('GET', 'search') and (not re.fullmatch(r'[A-Za-z0-9_~.-]+', arg) or arg in ('.', '..')):
            raise SafeError('Identifiers may contain only letters, digits, underscore, tilde, dot or hyphen.')
    prefix = PREFIX[product]
    def require(count):
        if len(args) != count:
            raise SafeError(f'{product} {command} expects {count} argument(s); see --help and api-cheatsheet.md.')
    if command == 'GET':
        require(1)
        return args[0]
    if product == 'bitbucket':
        if command == 'projects':
            require(0)
            return prefix + '/projects'
        if command == 'repos':
            require(1)
            return prefix + f'/projects/{args[0]}/repos'
        if command in ('prs', 'pr', 'diff', 'activities', 'comments', 'pr-comment'):
            require(2 if command == 'prs' else 3)
            path = prefix + f'/projects/{args[0]}/repos/{args[1]}/pull-requests'
            if command == 'prs':
                return path
            path += '/' + args[2]
            return path + {'pr': '', 'diff': '.diff', 'activities': '/activities', 'comments': '/comments', 'pr-comment': '/comments'}[command]
    if product == 'jira':
        if command == 'search':
            require(1)
            return with_query(prefix + '/search', {'jql': args[0]})
        if command in ('issue', 'comments', 'transitions', 'comment', 'transition'):
            require(1)
            return prefix + '/issue/' + args[0] + {'issue': '', 'comments': '/comment', 'transitions': '/transitions', 'comment': '/comment', 'transition': '/transitions'}[command]
    if product == 'confluence':
        if command == 'search':
            require(1)
            return with_query(prefix + '/content/search', {'cql': args[0]})
        if command in ('page', 'update-page'):
            require(1)
            path = prefix + '/content/' + args[0]
            return with_query(path, {'expand': 'body.storage,version'}) if command == 'page' else path
    raise SafeError('Unknown product command; see --help and api-cheatsheet.md.')


WRITES = {('bitbucket', 'pr-comment'): 'POST', ('jira', 'comment'): 'POST',
          ('jira', 'transition'): 'POST', ('confluence', 'update-page'): 'PUT'}


def validate_body(product, command, body):
    if not isinstance(body, dict):
        raise SafeError('Write body must be a JSON object.')
    valid = False
    if command in ('pr-comment', 'comment'):
        key = 'text' if product == 'bitbucket' else 'body'
        valid = set(body) == {key} and isinstance(body[key], str) and bool(body[key].strip())
    elif command == 'transition':
        transition = body.get('transition')
        valid = (set(body) == {'transition'} and isinstance(transition, dict) and set(transition) == {'id'}
                 and isinstance(transition['id'], str) and transition['id'].isdigit())
    elif command == 'update-page':
        version, content = body.get('version'), body.get('body')
        valid = (set(body) == {'type', 'title', 'version', 'body'} and body['type'] == 'page'
                 and isinstance(body['title'], str) and bool(body['title'].strip())
                 and isinstance(version, dict) and set(version) == {'number'}
                 and type(version['number']) is int and version['number'] > 1
                 and isinstance(content, dict) and set(content) == {'storage'}
                 and isinstance(content['storage'], dict) and set(content['storage']) == {'value', 'representation'}
                 and content['storage']['representation'] == 'storage' and isinstance(content['storage']['value'], str))
    if not valid:
        raise SafeError('Unsupported write body shape; see api-cheatsheet.md. Extra fields are refused.')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes arbitrary user input before credentials have been loaded.
        raise SafeError('Invalid command arguments. Run --help for syntax.')


def parser():
    p = Parser(description='Atlassian Server/DC reads and narrowly scoped, human-approved writes. Never pass credentials as arguments.')
    p.add_argument('product', choices=PRODUCTS)
    p.add_argument('command', help='GET, verify; Bitbucket projects/repos/prs/pr/diff/activities/comments/pr-comment; Jira search/issue/comments/transitions/comment/transition; Confluence search/page/update-page')
    p.add_argument('args', nargs='*')
    p.add_argument('--query', action='append', default=[], metavar='KEY=VALUE')
    p.add_argument('--all', action='store_true', dest='all_pages')
    p.add_argument('--max-pages', type=int, default=20)
    p.add_argument('--write', action='store_true')
    p.add_argument('--confirmed', action='store_true', help='Only after human approval of this request')
    p.add_argument('--body-file', type=Path)
    return p


def run(argv, redactor):
    p = parser()
    options = p.parse_args(argv)
    config = load_config(redactor)
    client = Client(options.product, config)
    if not 1 <= options.max_pages <= 100:
        raise SafeError('--max-pages must be between 1 and 100.')
    if options.command == 'verify':
        if options.args or options.write or options.body_file or options.confirmed or options.query or options.all_pages:
            raise SafeError('verify accepts no command arguments or write/pagination options.')
        paths = {'bitbucket': ['/rest/api/1.0/application-properties'],
                 'jira': ['/rest/api/2/serverInfo', '/rest/api/2/myself'],
                 'confluence': ['/rest/api/user/current']}[options.product]
        return {'checks': [{'path': path, 'result': client.request(path)} for path in paths]}
    path = route(options.product, options.command, options.args)
    query = {}
    for item in options.query:
        if '=' not in item or not item.split('=', 1)[0]:
            raise SafeError('--query requires KEY=VALUE.')
        key, value = item.split('=', 1)
        query[key] = value
    path = with_query(path, query)
    if options.product == 'bitbucket' and options.command == 'comments' and not dict(parse_qsl(urlsplit(path).query)).get('path'):
        raise SafeError('Bitbucket comments requires --query path=FILE. Use activities for general PR discussion.')
    method = WRITES.get((options.product, options.command))
    if method:
        if options.all_pages or options.query:
            raise SafeError('Writes do not accept pagination or query overrides.')
        if options.body_file is None:
            raise SafeError('Writes require a reviewable JSON --body-file.')
        try:
            body = json.loads(options.body_file.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            raise SafeError('Cannot read write body as JSON.') from None
        validate_body(options.product, options.command, body)
        summary = {'product': options.product, 'method': method, 'url': client.url(path), 'body': body}
        print(redactor.text('Request summary: ' + json.dumps(redactor.clean(summary), ensure_ascii=True)), file=sys.stderr, flush=True)
        if not options.write or not options.confirmed:
            raise SafeError('Write refused. Ask the human to approve this exact request, then use --write --confirmed.')
        return client.request(path, method, body)
    if options.write or options.confirmed or options.body_file:
        raise SafeError('Write options are valid only for the four documented write commands.')
    return read_pages(client, path, options.all_pages, options.max_pages)


def write_private(file, config):
    file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.tokens-', dir=file.parent)
    os.close(descriptor)
    try:
        if os.name == 'nt':
            # A new empty file: remove inheritance, then grant only the current Windows SID.
            result = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True, text=True, check=True)
            sid = re.search(r'S-1-[0-9-]+', result.stdout)
            if not sid:
                raise SafeError('Could not identify the current Windows SID. Nothing was stored.')
            subprocess.run(['icacls', temporary, '/inheritance:r', '/grant:r', '*' + sid[0] + ':F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        else:
            os.chmod(temporary, 0o600)
        content = '# Private Atlassian Server/DC credentials. Never source or show this file.\n'
        for key in sorted(KEYS):
            value = config.get(key, '')
            if any(c in value for c in '\n\r\x00'):
                raise SafeError('Configuration values cannot contain newline or NUL.')
            content += key + "='" + value.replace("'", "'\\''") + "'\n"
        Path(temporary).write_text(content, encoding='utf-8', newline='\n')
        os.replace(temporary, file)
    finally:
        Path(temporary).unlink(missing_ok=True)


def setup(redactor):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SafeError('Setup requires a human in an interactive terminal. Agents: ask the human to run setup-tokens.')
    file = config_path()
    config = load_config(redactor) if file.exists() else {}
    print('Configure each product you use. Enter keeps a stored value; - clears it. Blank URL skips an unused product.')
    for product in PRODUCTS:
        root = product.upper()
        for suffix, prompt in (
                ('BASE_URL', 'HTTPS base URL including context path'),
                ('USERNAME', 'Basic username (blank for Bearer PAT)'),
                ('TOKEN', 'PAT or Basic password (hidden)'),
                ('CA_BUNDLE', 'Custom CA PEM file (blank for system trust)'),
                ('INSECURE_TLS', 'Disable TLS verification? 1 = DANGEROUS, 0 = verify [default 0]')):
            key = f'{root}_{suffix}'
            if suffix != 'BASE_URL' and not config.get(f'{root}_BASE_URL'):
                config[key] = ''
                continue
            label = f'{product}: {prompt}' + (' [stored]' if config.get(key) else '') + ': '
            if suffix == 'TOKEN':
                # Refuse getpass fallback that could echo a password without terminal support.
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter('error', getpass.GetPassWarning)
                    answer = getpass.getpass(label)
            else:
                answer = input(label)
            config[key] = '' if answer == '-' else answer or config.get(key, '')
            if suffix == 'TOKEN':
                redactor.add(config[key])
        if config.get(root + '_BASE_URL'):
            # Validate before saving. No HTTP requests until the private file is in place.
            Client(product, config)
    if not any(config.get(p.upper() + '_BASE_URL') for p in PRODUCTS):
        raise SafeError('No products configured. Nothing was stored.')
    write_private(file, config)
    print('Private credentials saved. Checking configured products...')
    failed = False
    for product in PRODUCTS:
        if config.get(product.upper() + '_BASE_URL'):
            try:
                run([product, 'verify'], redactor)
                print(product + ': connectivity/authentication check passed')
            except Exception as exc:
                failed = True
                print(redactor.text(product + ': ' + str(exc)), file=sys.stderr)
    if failed:
        raise SafeError('Credentials saved, but a check failed. Correct the setup before using the agent.')


def main():
    redactor = Redactor()
    try:
        if sys.argv[1:] == ['setup']:
            setup(redactor)
        else:
            result = run(sys.argv[1:], redactor)
            print(json.dumps(redactor.clean(result), ensure_ascii=True, indent=2))
        return 0
    except (KeyboardInterrupt, EOFError):
        print('Cancelled.', file=sys.stderr)
        return 2
    except Exception as exc:
        # No traceback or unsanitized library debug output may cross the credential boundary.
        message = str(exc) if isinstance(exc, SafeError) else 'Local configuration or response error. Check setup and API compatibility.'
        print(redactor.text(message), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
