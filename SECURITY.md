# Security

## Reporting a vulnerability

Report vulnerabilities privately through GitHub: **Security > Report a vulnerability** on this repository, or open the form directly at <https://github.com/Metaheurist/SnapMem/security/advisories/new>. Please do not open a public issue. Include the SnapMem version (shown at the bottom of the sidebar, or the release tag), what you did, and what happened.

Only the latest release is fixed. Older EXEs are not patched.

## What the app handles

- **Signed links.** Export ZIP links and `memories_history.json` download links identify your Snapchat account. They are kept in memory, written to `urls.txt` only when you turn that on, and replaced with `<redacted>` in the activity log and error messages (`sc_memories_downloader/urls.py`).
- **Browser session.** "Keep me signed in" stores the Playwright browser profile in `%LOCALAPPDATA%\SnapMem\browser-profile`. It is off by default. The folder is not encrypted by the app, so other programs running as the same Windows user can read it. "Sign out" deletes it.
- **Network.** Only `https` URLs are fetched, including after redirects (plain `http` only for loopback addresses, used by the tests). The `scripts/preview_web.py` UI server listens on `127.0.0.1` only. Export links are accepted only from `storage.googleapis.com` with a `mydata~*.zip` file name, and Memory links only from `snapchat.com` and its subdomains.
- **ZIP files.** Extraction skips entries that would be written outside the target folder (`..`, absolute paths, drive letters) and streams each file instead of loading it into memory (`sc_memories_downloader/extract.py`).
- **Local files.** Settings live in `%LOCALAPPDATA%\SnapMem\settings.json`. Downloads, extracted files and the library live in the output folder you choose. Nothing is uploaded anywhere.

## Checks in CI

CodeQL (`security-extended`), Bandit, Gitleaks, pip-audit, OSV-Scanner, dependency review and OpenSSF Scorecard run from the workflows in `.github/workflows/`. Results appear under **Security > Code scanning**. Release builds include a CycloneDX SBOM and SHA256 checksums.

To check a downloaded EXE:

```powershell
Get-FileHash .\SnapMem-v1.2.3-win-x64.exe -Algorithm SHA256
```

Compare the hash with the line for that file in `SHA256SUMS.txt` on the same release.
