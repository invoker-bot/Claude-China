# Desktop signing setup

The v0.3.0 downloads do not have a verified publisher signature. macOS signing
and notarization are implemented in the builder, but require maintainer
credentials and a successful signed run on both Mac architectures before a
signed release can be claimed. Windows provider enrollment and integration are
pending. No SignPath application or approval is implied by this guide.

## Windows: free signing for an open-source project

An individual maintainer can apply to
[SignPath Foundation](https://signpath.org/apply.html) for qualifying open-source
software. This is a managed signing service: the certificate belongs to the
foundation and identifies it as publisher. It is not a personal certificate
that can be downloaded and used for arbitrary software.

Before applying, review the [current conditions](https://signpath.org/terms.html):

1. Publish the source under an OSI-approved license, describe the application,
   and provide an existing downloadable binary. This repository declares MIT
   and includes its full text in `LICENSE`; v0.3.0 provides a Windows installer.
   The licensing and distribution of bundled components also need review.
2. Enable MFA for GitHub and SignPath, and identify the people responsible for
   authoring, reviewing changes and approving signing.
3. Prepare a **Code signing policy** for the README and download pages, including
   the roles above and a privacy policy covering the launcher and relevant
   third-party components. After approval, add the attribution required by the
   foundation. Do not claim SignPath sponsorship before approval.
4. Apply using the project repository and release links. The foundation checks
   project control and reputation; being public and MIT-licensed alone does not
   guarantee acceptance.

Project links to include in the application:

- Source: <https://github.com/invoker-bot/Claude-China>
- Windows installer: <https://github.com/invoker-bot/Claude-China/releases/tag/v0.3.0>
- Native build instructions: `packaging/desktop/README.md`
- Build workflow: `.github/workflows/desktop-release.yml`

After acceptance, configure the approved SignPath project and GitHub integration.
Each production signing request requires approval by a designated maintainer.
The release integration must sign the project's launcher EXE, the Inno Setup
uninstaller and the final setup EXE, verify their Authenticode signatures, and
calculate checksums after signing. Use Inno Setup's `SignTool` and
`SignedUninstaller` integration for the uninstaller. Preserve Microsoft's
existing WebView2 signature. Do not re-sign third-party binaries as this project.

Self-signed certificates are free but not trusted by public Windows installations.
Even a valid public-trust signature cannot guarantee the absence of SmartScreen
reputation warnings. See Microsoft's
[code signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options).

## macOS: create and export the signing identity

An active Apple Developer Program account and a Mac are needed for initial
certificate setup. Use the Account Holder role for these steps.

1. In Keychain Access, use Certificate Assistant to create a certificate signing
   request, saved to disk.
2. Open [Certificates, Identifiers & Profiles](https://developer.apple.com/account/resources/certificates/list).
   Add a **Developer ID Application** certificate using that request.
3. Download the `.cer` and open it on the Mac where the request was created.
   In Keychain Access → My Certificates, confirm that the certificate expands
   to show its private key. Export that identity as a password-protected `.p12`.
4. Record the ten-character Team ID from the developer account.
5. At [Apple Account](https://account.apple.com/), create an app-specific password
   for notarization. Keep the account's two-factor authentication enabled.

The current distribution uses `.app` inside `.dmg`; it uses Developer ID
Application. A Developer ID Installer certificate is for a future `.pkg` format.
See [Apple's certificate instructions](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/).

## Configure GitHub Actions

In this repository's **Settings → Secrets and variables → Actions**, add:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `MACOS_CERTIFICATE_P12` | Single-line base64 of the exported P12, including its private key |
| Secret | `MACOS_CERTIFICATE_PASSWORD` | The P12 export password |
| Secret | `APPLE_ID` | The Apple Account email used for notarization |
| Secret | `APPLE_APP_SPECIFIC_PASSWORD` | The notarization app-specific password |
| Variable | `MACOS_TEAM_ID` | The ten-character Apple developer Team ID |

Keep certificate files outside the checkout, or in the ignored `.signing/`
directory. Do not paste private keys or passwords into issues, chat or commits.
For example, on the Mac, upload the P12 directly without printing it:

```bash
base64 -i /absolute/path/DeveloperID.p12 | tr -d '\n' |
  gh secret set MACOS_CERTIFICATE_P12 --repo invoker-bot/Claude-China
```

Set the remaining values in the GitHub UI, or use `gh secret set NAME` without
`--body` to enter secrets interactively.

Before a signed macOS release, run **Actions → Desktop installers → Run workflow**
with `macos_signing` enabled. This builds Actions artifacts without publishing a
release. Both Intel and Apple Silicon signing runs must pass before claiming
signed macOS distribution.
The v0.4.0 tag publishes Windows/Linux while macOS remains a CI artifact.
`SIGN_MACOS: 'false'` in the workflow permits ad-hoc macOS validation without
credentials. Set `SIGN_MACOS` to `true` to require signing on subsequent runs,
and `PUBLISH_MACOS` to `true` when including both DMGs in a release. Explicitly
requested signing never falls back to an ad-hoc package after a failure.

The workflow creates a temporary runner keychain, imports the identity and
validates the notary credentials. Only its certificate fingerprint, Team ID,
keychain path and notary profile name are passed to build steps. Cleanup restores
the prior keychain search list and removes the temporary keychain, including
after failures. PRs cannot use the signing secrets.

## What a signed macOS build verifies

`tools/build_desktop.py --smoke --signed` requires a Developer ID Application
identity, matching Team ID, notarization profile and successful native checks:

1. PyInstaller signs bundled native code with a secure timestamp and hardened
   runtime. The app allows JIT for PyObjC callbacks; it does not disable library
   validation. Signature errors fail the build.
2. `codesign` checks the app recursively, its certificate type, Team ID,
   timestamp and hardened runtime. The actual bundled GUI must start.
3. The app is submitted to Apple's notary service. Only an `Accepted` response
   permits stapling and ticket validation; Gatekeeper must accept the app.
4. The stapled app is copied into the DMG. The DMG is signed, notarized, stapled
   and assessed by Gatekeeper separately, then its checksum is calculated.
5. CI mounts the final disk image and runs the bundled GUI again.

The validation artifacts contain `signing.json` and notarization responses/logs.
They contain no P12 or keychain. A local unit-test pass is not proof of Apple
acceptance; the real signed workflow is the acceptance check.

For a local build with an identity and notary profile already in the keychain:

```bash
export MACOS_SIGNING_IDENTITY='Developer ID Application: YOUR NAME (TEAMID)'
export MACOS_TEAM_ID='YOUR_10_CHARACTER_TEAM_ID'
export MACOS_NOTARY_PROFILE='YOUR_EXISTING_NOTARYTOOL_PROFILE'
.venv/bin/python tools/build_desktop.py --smoke --signed
```

`MACOS_SIGNING_KEYCHAIN` can specify a non-default keychain containing the profile;
the signing identity must also be in the user's keychain search list.
macOS may still show the normal first-open confirmation for downloaded apps.
Signing and notarization do not remove that confirmation or requested system
permissions.
