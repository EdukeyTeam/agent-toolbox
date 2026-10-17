# One-time human setup

Run setup yourself in a local terminal. Credentials must never enter chat, logs,
shell arguments, a repository or a synced directory. Python 3.10+ is required;
there are no pip dependencies. Windows needs `python` or the `py -3` launcher.

## Create the credential

Use the application's profile/settings UI, not an agent:

- Bitbucket: personal access tokens (called HTTP access tokens in current releases),
  with project/repository read access only where needed and an expiry.
- Jira: Profile > Personal access tokens. Use a user whose project permissions fit
  the task; these tokens inherit that user's access.
- Confluence: Settings > Personal access tokens. Space/page restrictions still apply.

Bearer PATs are available in Bitbucket Server 5.5+, Jira Core/Software 8.14+
(Jira Service Management 4.15+) and Confluence 7.9+. Check the installed version
and administrator policy. For legacy installations or proxies that require HTTP
Basic, set the product username; the TOKEN field then holds that user's password
or a server-supported app password/PAT. Cloud app passwords/API tokens are not
interchangeable with Server credentials. SSO or a disabled Basic provider may
require administrator configuration; the wrapper never silently falls back.
See the [version sources](api-cheatsheet.md#version-and-authentication-sources).

## Store and verify

Linux/macOS:

```bash
bash "<skill-dir>/scripts/setup-tokens.sh"
```

Windows PowerShell:

```powershell
pwsh -NoProfile -File "<skill-dir>/scripts/setup-tokens.ps1"
```

The shared Python setup prompts for each product. Blank URL skips an unused
product. Enter keeps a stored value; `-` clears it. Token/password input is hidden
and setup refuses to run without an interactive terminal. You can rerun it to rotate
credentials. No token is displayed, including when connectivity checks fail.

The file uses quoted data assignments, never executable shell code. Keys per product:

| Prefixes | Suffix | Meaning |
| --- | --- | --- |
| BITBUCKET, JIRA, CONFLUENCE | BASE_URL | HTTPS base including context, e.g. `https://git.example.com/bitbucket`; no trailing `/rest/api`, userinfo, query or fragment |
| same | TOKEN | Bearer PAT, or Basic password when USERNAME is set |
| same | USERNAME | Empty for Bearer; nonempty selects Basic explicitly |
| same | CA_BUNDLE | Optional absolute path to a trusted internal CA PEM bundle |
| same | INSECURE_TLS | Empty or `0` verifies TLS; `1` disables certificate AND hostname verification |

Setup writes `~/.config/atlassian-onprem/tokens.env`, or
`%USERPROFILE%\.config\atlassian-onprem\tokens.env` on Windows. New files are private
before secrets are written, then atomically replace the previous file. POSIX uses
mode 600 (new directory 700); Windows removes inheritance and grants only the current
user SID on the new file. Administrators can still take ownership. The runtime
refuses POSIX files owned by another user or accessible to group/others.

`ATLASSIAN_PROFILE` optionally selects `tokens.<profile>.env`; names contain only
letters, digits, underscore or hyphen, at most 40 characters. Use the same profile
for setup and reads. `ATLASSIAN_CONFIG_DIR` overrides the directory, useful for an
organization's approved private storage. Do not put either path in a shared/synced
folder. The agent must only check that the selected file exists.

Checks after saving: Bitbucket `/rest/api/1.0/application-properties`; Jira both
`/rest/api/2/serverInfo` and `/rest/api/2/myself`; Confluence
`/rest/api/user/current`. Public metadata endpoints alone do not prove repository
permissions; try the intended read after setup. Failures preserve the saved file
and return nonzero, so correct the credential, URL, trust chain or permissions.

## Internal certificates and networking

Ask your administrator for the CA PEM file and choose it at the CA_BUNDLE prompt.
TLS verification is on by default. **INSECURE_TLS=1 is a dangerous opt-out:** anyone
able to intercept the connection could steal the credential. Setup and each call
print a warning on stderr. Only the human may deliberately select this in setup;
agents must never enable it to work around a failure. It does not permit remote
plain HTTP. HTTP loopback is allowed solely for local fake-server tests.

Connect the company VPN first. Redirects (including SSO logins) are refused, and
HTTP_PROXY/HTTPS_PROXY are ignored so credentials cannot be forwarded to an
unconfigured proxy. Organizations that require an explicit proxy need a reviewed
extension; do not replace these calls with ad hoc curl commands carrying secrets.

## Enforce the boundary in the agent

Deny direct reads of `~/.config/atlassian-onprem/**` in the agent's permission
settings as well as following SKILL.md. For Claude Code, merge this into its
existing settings without overwriting other rules:

```json
{"permissions":{"deny":["Read(~/.config/atlassian-onprem/**)"]}}
```

Adjust the denied directory for custom config locations. Also require approval
for invocations containing `--write`, using the agent's command approval controls.
Both flags can be supplied by software; server permissions and human review are
the actual safeguards. Start with a read-only service user where possible.

To remove access, revoke the token in the product UI and remove/rotate the local
credential yourself. If a token enters chat or logs, revoke it before continuing.
