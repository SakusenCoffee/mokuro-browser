# Signing public installers

Signing identifies the publisher; it does not guarantee that every operating
system confirmation disappears. The current release workflow builds unsigned
installers. Keep the README's unsigned download instructions until the actual
Windows and both Mac downloads have been replaced with verified signed builds.

## Windows

For an eligible individual publisher, Microsoft's recommended route for downloads
outside the Store is [Azure Artifact Signing](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)
(formerly Trusted Signing), starting at approximately US$9.99/month. Individuals
are currently eligible in the US and Canada; see the linked page for organizational
eligibility and current pricing. A trusted CA code-signing certificate is another
option when Azure is unavailable. A self-signed certificate will not establish
public trust on other people's computers.

For a free open-source option, you can [apply to SignPath Foundation](https://signpath.org/apply.html).
They provide Windows code signing to approved projects under their
[eligibility and signing conditions](https://signpath.org/terms.html). Approval
is required; having a public repository alone does not activate signing.
This project has not applied or been approved. Follow their CI integration
requirements if accepted, instead of the Azure steps below.

1. Create an Azure subscription and an Artifact Signing account, complete
   identity validation, and create a **Public Trust** certificate profile using
   [Microsoft's setup guide](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart).
2. Give the release signing identity the **Artifact Signing Certificate Profile
   Signer** role. Use the service's GitHub Actions integration, preferably with
   Azure login through GitHub OIDC, following
   [the official signing action](https://github.com/Azure/artifact-signing-action).
   The workflow needs `id-token: write` for OIDC. Configure the trusted repository
   and release environment in Azure rather than storing an Azure account password.
3. Sign `dist/MokuroBrowserSetup-windows-x64.exe` **after** the PyInstaller build
   and **before** uploading it. Use SHA256 and the service's RFC3161 timestamp.
   Supply the Azure account endpoint, signing account and Public Trust profile
   to the action. The existing workflow must be updated to perform this step;
   merely creating the account or adding GitHub secrets does not sign a release.
4. On a Windows machine, verify the downloaded final executable:

   ```powershell
   Get-AuthenticodeSignature .\MokuroBrowserSetup-windows-x64.exe | Format-List Status,SignerCertificate,TimeStamperCertificate
   ```

   Its status should be `Valid`, with the expected verified publisher. Also run
   `signtool verify /pa /v` against the executable with Windows SDK SignTool.

Microsoft states that [SmartScreen reputation builds over time](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options).
A new signed file can still show a warning. Keep the same publisher identity
across releases and avoid promising warning-free Windows downloads.

## macOS

Join the [Apple Developer Program](https://developer.apple.com/programs/)
(US$99/year, or local currency). Generate a **Developer ID Application**
certificate with its private key, and import it into the build Mac's keychain.
The free personal development certificate does not replace Developer ID signing
for public downloads. Apple explains the process in
[Signing Mac Software with Developer ID](https://developer.apple.com/developer-id/).

Build **each architecture** with the actual identity from that keychain:

```console
python tools/build_installer.py --codesign-identity "Developer ID Application: Your Legal Name (TEAMID)"
```

The option is passed to PyInstaller during the build, enabling its hardened
runtime signing and signing the embedded Python libraries and uv binary too.
This is needed for a one-file installer: signing only the outer `.app` afterward
does not fix unsigned embedded binaries. See
[PyInstaller's signing documentation](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing).

Use Apple's [notarytool process](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
to submit the resulting ZIP, wait for acceptance, staple the ticket to the app,
then recreate the ZIP so the downloadable file contains the ticket. For Apple
silicon, with a previously configured `mokuro-notary` keychain credential profile:

```console
xcrun notarytool submit dist/MokuroBrowserSetup-macos-arm64.zip --keychain-profile mokuro-notary --wait
xcrun stapler staple build/installer-dist/MokuroBrowserSetup.app
xcrun stapler validate build/installer-dist/MokuroBrowserSetup.app
codesign --verify --deep --strict --verbose=2 build/installer-dist/MokuroBrowserSetup.app
spctl --assess --type execute --verbose=4 build/installer-dist/MokuroBrowserSetup.app
ditto -c -k --sequesterRsrc --keepParent build/installer-dist/MokuroBrowserSetup.app dist/MokuroBrowserSetup-macos-arm64.zip
```

Repeat on the Intel build, using its `macos-x64.zip` name. If notarization is
rejected, inspect the notarytool log and resolve it before publishing. Verify
both final ZIPs after downloading and extracting them on a clean Mac with
normal Gatekeeper settings. An ordinary first-open internet-download confirmation
can still appear; the goal is to eliminate the unidentified-developer bypass.

For CI automation, import the certificate/private key into a temporary keychain
and supply notarization credentials through protected GitHub Actions secrets
or an App Store Connect API key. Keep private keys and passwords out of source,
release assets and chat. The build flag is ready; certificate import, notarization
and ticket stapling still need to be configured for your publisher account.

## Linux AppImages and browser extensions

An AppImage can carry an optional GPG signature using
[appimagetool's signing support](https://docs.appimage.org/packaging-guide/optional/signatures.html).
Linux desktop environments do not share an Apple/Microsoft-style publisher
certificate system; that signature does not sign the Windows or Mac downloads.
Current release assets include SHA256 checksums and remain unsigned.

Installer signing also does not sign the Firefox extension. A permanent Firefox
installation requires Mozilla add-on signing; Chrome distribution uses the Chrome
Web Store. Those are separate from the desktop executable's publisher identity.
