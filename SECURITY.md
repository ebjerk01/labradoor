# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities **privately**, not as a public issue.

Use GitHub's private vulnerability reporting: on this repository, open the **Security** tab → **Report a vulnerability**. This creates a private advisory visible only to you and the maintainers. (See GitHub's [guide to privately reporting a vulnerability](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability).)

We'll acknowledge the report, work with you on a fix, and credit you in the advisory unless you'd rather stay anonymous.

## Scope

Labradoor's job is to put infrastructure behind one login with roles, so the security-sensitive surface is:

- the **gateway** (`gateway/lab/`): authentication, sessions, role and `owner_only` enforcement, request signing, the proxy, and owner approvals;
- the **module system**: a module must reach a backend only through the routes it declares, and must never expose a credential or a privileged action it didn't declare;
- the **connectors** (`connectors/`): each isolates one backend's credential.

The security model is documented in `docs/modules.md` (routes, roles, `owner_only`, request signing) and `docs/login.md` (accounts, two-factor login, SSO, owner approvals).

## Supported versions

Labradoor is pre-release. Fixes land on `main`; until 0.1.0 there is no separate maintenance branch.
