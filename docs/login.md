# Login

Labradoor has its own accounts and can also use single sign-on (SSO). You can run it with local accounts only, with SSO
only, or with both. This page covers:

- the first run;
- local accounts and two-factor login (2FA);
- connecting an OpenID Connect provider (Authentik, Keycloak, and others);
- how roles are mapped;
- how long sessions last, and what happens when someone is removed.

## Roles

Every account has one of three roles.

| role | can |
|---|---|
| **owner** | Everything. Only an owner can manage accounts, login settings, module settings and connections, and approve owner-only actions. |
| **admin** | Reads everything except routes marked `secret`. Can make changes, except on owner-only routes. For those, the admin sends the owner an "ask owner" request, which the owner approves or denies once. |
| **guest** | Sees only the modules that one of their **groups** unlocks (Settings → `~/modules` → (expand the module) → access). |

Every change is written to the audit log (the Log view, or `lab-admin audit`).

## First run

A fresh installation has no owner. When the installer finishes, it prints a **one-time setup link** and keeps it in
`/etc/lab/setup-link` (readable by root only):

```
FIRST RUN — Open this link within 1 hour to create the owner account (it works once):

  https://labradoor.example.com/setup#4mYk…
```

The link is never written to a log, because logs are often shipped to a log server that other people can read. While
no owner exists, the gateway's log (`journalctl -u lab`) only says where to find the link.

How the link works:

- **One use, one hour.** The token after `#` works once and expires after an hour. The browser never sends the part after
  `#` to a server, so the token stays out of proxy and access logs. The setup page also removes it from the address bar.
- **Only a hash is stored.** The database keeps a hash of the token, not the token itself.
- **Only the newest link works.** A new link makes every older one invalid. To get a new link, run this on the Proxmox
  host (`ID` = the Labradoor container), or `lab-admin setup-link` as root inside the container:

  ```
  pct exec ID -- lab-admin setup-link
  ```

- **Reloading is fine, copying the address is not.** The page keeps the token for this browser tab only. If you open
  `/setup` without the `#…` part, it says there is no token in the address: open the whole link again.

- **Nothing else can create the owner.** Every account route needs a logged-in owner. Until the first owner exists,
  the setup page is the only way in.
- **The setup page goes away after use, for good.** Once an owner exists, the setup route answers `404` and
  `lab-admin setup-link` refuses to run (and deletes `/etc/lab/setup-link`, which updates do too; the spent link in it
  opens nothing). From then on, owners add people in **People**.
- **It never reopens by itself.** Labradoor remembers that an owner has existed. If later no owner is active (the only
  owner was an SSO user who lost the owner group, or was disabled), the setup page stays closed and updates do not make
  a new link. Recovery is root's decision, on the host:

  ```
  lab-admin user NAME --enable            # a disabled owner
  lab-admin passwd NAME --role owner      # make an existing account owner again (sets a local password)
  lab-admin setup-link --recover          # only if you really want a NEW owner account through the setup page
  ```

  `--recover` makes one link, valid for an hour, and the audit log records it.

The setup page asks for:

- a username;
- an optional display name;
- a password of at least 12 characters (a strength hint shows as you type);
- optionally, 2FA. This is on by default. Scan the QR code with an authenticator app (for example Aegis, 2FAS,
  Google Authenticator or 1Password) and type the 6-digit code it shows.

If you turn on 2FA, the page then shows **10 recovery codes**. Save them, for example in a password manager. They are
shown only this once.

If the setup link has expired, use the console or SSH to run `lab-admin setup-link` as root. It prints a fresh link
and writes it to `/etc/lab/setup-link`.

## Local accounts

Owners manage local accounts in **People**:

- **+ local account**: enter a username, display name, first password, role, and guest groups (comma separated).
- **edit** an account to:
  - change its role or groups;
  - set a new password (this ends the person's sessions);
  - reset 2FA when someone loses their phone (this ends their sessions);
  - turn SSO login on or off for the account;
  - log the person out;
  - disable the account (it can't log in, and its sessions end at once);
  - delete the account.
- **Safety rules.** You can't demote, disable or delete yourself, and you can't remove the last active owner.

Each person manages their own login under **Settings → `~/account`**: they can change their password, turn 2FA on or off,
and make new recovery codes.

The same tasks from the command line, as root inside the Labradoor container (`pct enter ID`, or `pct exec ID -- lab-admin …`):

```
lab-admin users                         # every account: role, local password, sso, 2fa, disabled
echo 'a long passphrase' | lab-admin passwd alice --role guest   # create a local account, or set a new password
lab-admin user alice --disable          # also --enable, --reset-2fa
lab-admin revoke alice                  # end alice's sessions
```

### Passwords

Passwords must be at least 12 characters long and not too repetitive. They are stored with **scrypt**
(`hashlib.scrypt`, N=2^15, r=8, p=1) and a random salt for each user. The scrypt parameters are stored with each hash.
When someone logs in with an older or weaker hash (for example the PBKDF2 hashes of early versions), the hash is
upgraded to the current parameters at that login.

Failed logins are throttled per client IP: after `LAB_LOGIN_ATTEMPTS` failures (default 5), that IP must wait 15 minutes.
The client IP is taken from `X-Real-IP` or `X-Forwarded-For` only when the request comes from one of
`LAB_TRUSTED_PROXIES` (none by default). A loopback address there counts only together with `LAB_PROXY_SECRET`:
connectors run on the same host and reach the gateway from `127.0.0.1` too, so without the secret one of them could
pick a fresh client address for every attempt ([install.md](install.md#behind-a-reverse-proxy)).

### Two-factor login (TOTP)

- **Standard.** Codes follow RFC 6238: HMAC-SHA1, 6 digits, a new code every 30 seconds. Any authenticator app works.
- **Clock drift.** The gateway also accepts the code from one step before or after the current one.
- **Each code works once.** Once a code has been accepted, it and every older code are refused.
- **The secret is encrypted.** The TOTP secret is stored encrypted with the gateway's master key
  (`/etc/lab/master.key`, the same key that seals module secrets). Without the master key, accounts with 2FA can't log
  in, so keep a copy of the key somewhere safe.
- **Recovery codes.** There are 10 recovery codes. Only their hashes are stored, and each one works once. To use one,
  type it in place of the 6-digit code. **Settings → `~/account` → new recovery codes** replaces them all.
- **Lost phone, no codes left.** An owner can reset the person's 2FA in People. On the server, use
  `lab-admin user NAME --reset-2fa`.

**Requiring 2FA.** The owner can turn on **Settings → `~/login` → require 2FA for owners/admins**.

- When it is on, an owner or admin who logs in with a local password and has no 2FA must set up 2FA first. Until they
  do, every API call except the enrolment ones is refused.
- Guests are not affected.
- SSO logins are not affected either: 2FA for them is the login service's job.
- An owner who logs in locally must have 2FA on their own account before they can turn this setting on.

## Single sign-on (OpenID Connect)

Labradoor uses the authorization code flow with PKCE (S256).

- **Users.** The username comes from the `preferred_username` claim. It must be a plain Labradoor username (2-64
  characters: ASCII letters, digits, `.` `_` `@` `-`; no spaces, no look-alike Unicode letters), or the login is
  refused. A **new** SSO user whose name differs from an existing account only in upper/lower case is refused too
  (`Admin` next to `admin`): most backends treat those as the same person. The same rule applies to local accounts.
- **Roles.** Groups come from the `groups` claim.
- **Token check.** The ID token is fetched by the server directly from the token endpoint. The gateway then checks the
  issuer, audience, expiry and nonce.

### Configure it in the UI

As the owner, open **Settings → `~/login`**:

| field | what to enter |
|---|---|
| issuer URL | The provider's issuer, exactly as its discovery document gives it. Click **test issuer** to fetch `<issuer>/.well-known/openid-configuration` and check it. |
| client id / client secret | The confidential client you created at the provider. The secret is stored encrypted with the master key. The page never shows it again; it only says whether one is stored. |
| button name | The text on the login button: "sign in with …". If empty, the issuer's host name is used. |
| owner group / admin group | The provider groups that give the owner and admin roles. The defaults are `lab-owners` and `lab-admins`. |
| redirect URI | Shown on the page. Copy it into the provider's client settings. It is `LAB_PUBLIC_URL` + `/auth/callback`, so set `LAB_PUBLIC_URL` correctly. |

When you save, SSO is active right away. To turn SSO off, clear the issuer URL.

### Configure it in the environment

Any field can also be set in `/etc/lab/lab.env`:

| setting | environment variable |
|---|---|
| issuer URL | `LAB_OIDC_ISSUER` |
| client id | `LAB_OIDC_CLIENT_ID` |
| client secret | `LAB_OIDC_CLIENT_SECRET` |
| button name | `LAB_OIDC_NAME` |
| owner group | `LAB_OWNER_GROUP` |
| admin group | `LAB_ADMIN_GROUP` |
| require 2FA for owners/admins | `LAB_REQUIRE_2FA` |
| SSO session length (days) | `LAB_SESSION_DAYS` |
| local session length (days) | `LAB_LOCAL_SESSION_DAYS` |
| SSO session cap (hours) | `LAB_SSO_MAX_AGE_HOURS` |

**A value set in the environment wins.** Settings shows that field as locked, with the variable's name. This suits
installations managed as code. An empty variable counts as not set.

### Example: Authentik

1. **Create the provider.** Go to Applications → Providers → **Create** → OAuth2/OpenID Provider:
   - client type: **Confidential**;
   - redirect URI: the one shown in Settings → `~/login` (strict match);
   - scopes: `openid`, `profile`, `email`. Authentik's default `profile` scope mapping already includes `groups`.
2. **Create the application.** Go to Applications → **Create**. Choose the provider above and pick a slug, for example
   `labradoor`.
   - If you bind no policy, every Authentik user may log in, and the role decides what they see.
   - If you bind a group, only that group may log in.
3. **Create the role groups.** Make two groups, `lab-owners` and `lab-admins`, or use your own names and enter them in
   Settings.
4. **Fill in Settings → `~/login`:**
   - issuer: `https://auth.example.com/application/o/labradoor/` (the provider page shows it as "OpenID Configuration Issuer");
   - client id and client secret: from the provider page.

### Example: Keycloak

1. **Create the client.** In your realm, go to Clients → **Create client**:
   - client type: OpenID Connect;
   - client authentication: **on** (confidential);
   - authentication flow: standard flow only;
   - valid redirect URIs: the redirect URI from Settings → `~/login`.
2. **Turn on PKCE.** In the client's Advanced tab, set **Proof Key for Code Exchange Code Challenge Method** to S256.
3. **Send the groups.** Go to Client scopes → `<client>-dedicated` → Add mapper → By configuration → **Group Membership**:
   - token claim name: `groups`;
   - full group path: **off** (Labradoor compares plain group names);
   - add to ID token: on.
4. **Create the role groups.** Make two groups, `lab-owners` and `lab-admins`, or use your own names.
5. **Fill in Settings → `~/login`:**
   - issuer: `https://keycloak.example.com/realms/<realm>`;
   - client id: the client's id;
   - client secret: from the Credentials tab.

Other providers (Zitadel, Dex, Okta, Entra ID, …) work the same way. They must send `preferred_username` in the ID
token, and `groups` too if you want owner or admin roles. Without `groups`, every SSO user is a guest.

### Role mapping

| SSO groups contain | role |
|---|---|
| the owner group | owner |
| the admin group (and not the owner group) | admin |
| neither | guest. Their groups decide which modules they see (Settings → `~/modules` → (expand the module) → access). |

- **Roles are read at every SSO login.** For an SSO account, People shows the role and groups, but the next SSO login
  replaces them with the provider's.
- **Change SSO roles at the provider.** For example, move the person between groups there.
- **Local accounts keep what the owner sets.**

### Linking an account to SSO

A local account and an SSO identity with the **same username** can be the same account, so one person can use either
login. A local account is not linked by default, so that an SSO user can't take over (or demote) a local owner just by
having the same name.

| account | can it log in with SSO? |
|---|---|
| a new SSO user (no account here yet) | Yes. The account is created and linked automatically. |
| a local account with SSO login **off** (the default for accounts made in People or at first run) | No. The SSO login is refused: "a local account with this name exists". To allow it, the owner opens People → edit → **sso login on**. |
| a disabled account | No, by either login. |

**Break-glass.** If an SSO account also has a local password (`lab-admin passwd NAME`), the person can still log in when
the provider is down. Use **Local account** on the login page.

## Sessions and role refresh

| setting | default | applies to |
|---|---|---|
| SSO session (days) | 14 | sessions started with SSO |
| local session (days) | 1 when SSO is configured (break-glass use), else the SSO value (14) | sessions started with a password |
| SSO session cap (hours) | 24 | SSO sessions, when roles are not refreshed (see below) |

New lengths apply from the next login. Owners can end anyone's sessions in People → edit → log out, or with
`lab-admin revoke NAME`. A disabled account's sessions end at once.

### What happens when someone is removed at the provider

The gateway checks SSO sessions every 5 minutes (`LAB_ROLESYNC_SECONDS`). What that check can do depends on the provider.

**If the authentik module is configured** (Settings → `~/modules` → authentik, with an API token that may view users), the
check asks Authentik for each signed-in SSO user's groups and active flag:

- If someone's groups changed, their role changes from their next request.
- If someone was deactivated or deleted, their sessions end.
- If Authentik can't be reached, nothing changes, so an outage doesn't log everyone out.

**With any other provider**, roles are not refreshed. OpenID Connect has no portable way to read a user's groups
without their browser. So SSO sessions are **capped**:

- A new SSO session lasts at most the SSO session cap (24 h by default).
- The check ends SSO sessions older than the cap.
- When someone logs in again, their groups are read fresh.

So a person removed from the provider, or moved out of the admin group, loses access within the cap. Lower the cap
(down to 1 hour) for faster removal. When the provider still has a session for that person, logging in again only
takes a redirect.

Local sessions are never touched by this check, since local accounts have no SSO groups. Settings → `~/login` shows which
mode is active under **role refresh**.

## Files and storage

| what | where |
|---|---|
| accounts, sessions, setup token hash, login settings | the gateway database (`LAB_DB`). Passwords are scrypt hashes; recovery codes and the setup token are SHA-256 hashes. |
| TOTP secrets and the SSO client secret | the same database, encrypted with `/etc/lab/master.key`. Keep a copy of the master key apart from database backups. |
| login settings set in the environment | `/etc/lab/lab.env` |
