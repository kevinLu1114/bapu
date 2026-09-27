# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |

Until 1.0, only the latest release receives fixes.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately through GitHub's
private vulnerability reporting: open the repository's **Security** tab and choose **Report a
vulnerability**, or go directly to
<https://github.com/kevinLu1114/bapu/security/advisories/new>.

Please include what you found, how to reproduce it (ideally offline), and the impact you see.
The report stays private between you and the maintainer until a fix is released; you will be
credited in the advisory unless you prefer not to be.

## Scope notes

- **Online mode sends content to a third-party API.** With `--online` and `TYPESAFE_API_KEY`
  set, `bapu-gate` sends requirement and scenario text, and `bapu-findings` sends claims and
  their evidence, to `https://api.typesafe.ai`. Do not use online mode on content that contains
  secrets. Offline mode, the default, makes no network call.
- **The API key** is read from the environment only. It is never written to receipts, logs or
  output, and the client refuses redirects so the key is never resent to another host.
- **`bapu-seedred` executes code.** It edits the files named in its table and runs the
  project's tests. Run it only on code and tables you trust.
