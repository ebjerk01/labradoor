## What this changes

<!-- A short description of the behaviour change and why. -->

## Checklist

- [ ] All gates pass locally (`npm run build`, the Python suites, the node `*.test.mjs` — see [CONTRIBUTING.md](../CONTRIBUTING.md))
- [ ] No installation-specific data in any manifest or UI (URLs, IPs, hostnames, tokens, IDs, user/group names)
- [ ] New or changed modules declare every interface they use; dangerous actions are `owner_only` with a label
- [ ] No new server dependencies (the gateway is standard-library Python)
- [ ] Docs updated if behaviour or the module API changed
