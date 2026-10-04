# One-time setup

The user does these steps themselves, once per machine. The agent explains them and waits; it never handles a token.

## 1. Check Node.js

```bash
node --version
```

Version 18 or newer is needed. If it is missing, install the current LTS release from <https://nodejs.org/> (or with `winget install OpenJS.NodeJS.LTS` on Windows, `brew install node` on macOS, or the distribution's package manager on Linux).

## 2. Create a read-only API token

In the [Cloudflare dashboard](https://dash.cloudflare.com/):

1. Open **Manage Account → Account API Tokens** and choose **Create Token**. An account-owned token keeps working when the person who created it leaves the account, and the audit log shows the token rather than a person. If that menu is not available to you, **My Profile → API Tokens** creates a user-owned token, which works too.
2. Pick the **Read all resources** template. To limit the agent to certain products or zones, create a custom token with only the matching `Read` permissions instead.
3. Set an expiry (a year is reasonable) and create the token. Cloudflare shows the token once; keep that page open for the next step.

Also note the account ID: the 32-character ID in the dashboard address, `dash.cloudflare.com/<account-id>/...`.

## 3. Store it

In your own terminal, not through the agent:

```bash
node "<skill-dir>/scripts/setup-tokens.mjs"
```

It asks for the account ID and the read token (input is hidden), leaves the write token empty unless you supply one, saves the file so that other users of the machine cannot read it (on Windows, the system account and administrators keep access, as with any file), and checks that the token works. Run it again at any time to replace a value; pressing Enter keeps the stored one.

The file is `~/.config/cloudflare/tokens.env` on every system (on Windows, `C:\Users\<you>\.config\cloudflare\tokens.env`). Set the `CLOUDFLARE_TOKENS_FILE` environment variable before running the scripts to keep it elsewhere. Keep it out of synced folders (OneDrive, Dropbox, iCloud) and out of any repository.

## 4. Stop the agent reading the file

The skill tells the agent never to open the credentials file. Back that up with your agent's own controls, so the rule does not depend on the agent following instructions. In Claude Code, add a deny rule to `~/.claude/settings.json`:

```json
{
  "permissions": {
    "deny": ["Read(~/.config/cloudflare/**)"]
  }
}
```

Other agents have equivalent ignore or deny settings; use them for the same path.

## Optional: let the agent apply approved changes

Skip this unless you have decided you want it. With only a read token, the worst a confused or manipulated agent can do is read your configuration.

A write token lets the agent send a change after you reply `approved` to its proposal. The approval is a rule the agent follows, not something Cloudflare enforces, so limit what the token itself can do:

1. Create a second token with `Edit` permission only for what the agent should change (for example DNS and WAF on one zone), a short expiry, and no account, member, billing or API-token permissions.
2. Run `setup-tokens.mjs` again and enter it at the write-token prompt.
3. Make your agent ask before every run of the apply script. In Claude Code:

```json
{
  "permissions": {
    "ask": ["Bash(node *cf-apply.mjs*)"]
  }
}
```

To disable writes again, run `setup-tokens.mjs` and type `-` at the write-token prompt, then delete the token in the dashboard.

## Rotating or removing

Create a new token in the dashboard, run `setup-tokens.mjs` to store it, and delete the old token in the dashboard. To remove the setup completely, delete the tokens in the dashboard and then delete the credentials file.
