# Security and verification

## Verify a release

From 1.4.0 on, every release carries an [artifact attestation](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds) that cryptographically binds the ZIP file to the source code and to the GitHub Actions workflow that built it. Releases up to 1.3.0 have no attestation.

`onesti_lock.zip` is also the file HACS downloads and installs (`zip_release` is set in `hacs.json`), not just an attachment on the release page. The attestation therefore covers exactly what ends up in `custom_components/onesti_lock/` on your system.

### What the ZIP leaves out

The ZIP is not the whole component directory. `ZIP_EXCLUDE` in `scripts/release_publish.py` leaves out `ble/` and `bluetooth.py`, the Bluetooth library written from the vendor's app. Nothing the integration loads imports it, and `ble/client` holds the credential a factory-reset lock accepts as its owner, so installing it would put an admin client for such a lock on every user's system for a feature that does not exist. The code is still in the repo and in the tag's source tree, and the build refuses to pack a module that imports something it leaves out.

### Why

A custom integration in Home Assistant runs with full access to your system. You should be able to check that the code you install really comes from the source you can read on GitHub.

### Verify with the GitHub CLI

1. Download `onesti_lock.zip` from [the latest release](https://github.com/fredrik-lindseth/onesti-lock/releases/latest).

2. Verify the attestation:

   ```bash
   gh attestation verify onesti_lock.zip --repo fredrik-lindseth/onesti-lock
   ```

3. You should see something like:

   ```text
   ✓ Verification succeeded!
   ```

   The output names the commit and the workflow that built the file.

### Verify the SHA256 checksum

Every release note carries the SHA256 of the ZIP along with the commit it was built from. Check that the file you downloaded matches:

```bash
shasum -a 256 onesti_lock.zip   # sha256sum on Linux, shasum on macOS
```

Compare the output with the checksum in the release note.

### Build the ZIP yourself and compare

The build is deterministic: the ZIP is packed from the git objects at the commit the tag points at, with fixed timestamps and permissions taken from git. So you can build the same file yourself and get the same sha256, without trusting either us or GitHub:

```bash
git clone https://github.com/fredrik-lindseth/onesti-lock
cd onesti-lock
python3 scripts/release_publish.py build --sha vX.Y.Z --output /tmp/onesti_lock.zip
```

The output is the sha256. It should be identical to the one in the release note and to the one you downloaded.

To check the whole chain in one call, that is, that the tag, the ZIP and the attestation point at the same artifact:

```bash
just release-verify vX.Y.Z
```

Releases up to 1.3.0 were published before this flow existed. They do carry an `onesti_lock.zip`, but it was packed outside the release workflow and is not what HACS installed: HACS took those versions from the tag's source tree. Nothing binds those files to a build, so `just release-verify` fails on them, and that is the correct answer.

## Reporting a security problem

Found something security related? Open an issue on [GitHub](https://github.com/fredrik-lindseth/onesti-lock/issues), or contact the maintainer directly. Do not put a working exploit or a real PIN in a public issue.
