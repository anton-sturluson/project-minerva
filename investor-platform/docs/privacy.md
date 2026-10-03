# Privacy and repository hygiene

Keep account-specific configuration in environment variables, and keep source exports, database dumps and screenshots in ignored local storage. Commit synthetic fixtures and reserved example email addresses only. The local database password in the quick start is a development example, not a production secret. ([Ignore rules](../../.gitignore), [Tailscale configuration](tailscale.md))

## Before publishing changes

From the repository root:

```sh
python3 scripts/check_repo_privacy.py
```

The check examines tracked files for personal home paths, non-example email addresses, private tailnet addresses, document-sharing identifiers and sensitive filenames. It reports locations without printing values. CI also runs a checksum-verified Gitleaks release against the tracked-file snapshot. Ignored local files are not uploaded or scanned by this workflow. ([Privacy check](../../scripts/check_repo_privacy.py), [CI](../../.github/workflows/privacy.yml))

Use `example.com`, `example.org`, `example.net` or `example.invalid` in sample contact information. Use repository-relative paths or `/path/to/...` placeholders. Configure Git to use a GitHub no-reply email before making commits. Never paste suspected secrets into issues, PR descriptions, screenshots or scan logs.

## Existing exposure

Removing a value from the latest file does not remove it from Git history, old branches, PR diffs, forks or clones. Author and committer metadata may also contain personal details. History cleanup requires reviewing all affected refs and coordinating rewritten commits with collaborators. Hosting-provider caches may require a separate removal request.

If a real credential has been published, revoke or rotate it first; deleting Git content cannot make that credential safe again. Automated scans detect known patterns and cannot prove that every form of private information is absent.

## References

- [Root ignore rules](../../.gitignore) — excluded local configuration, key files and database artifacts.
- [Privacy check](../../scripts/check_repo_privacy.py) and [CI workflow](../../.github/workflows/privacy.yml) — current tracked-file safeguards.
- [Gitleaks](https://github.com/gitleaks/gitleaks) — secret-pattern scanner.
