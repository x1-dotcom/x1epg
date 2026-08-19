# X1 EPG signing keys

X1 EPG uses Ed25519 signatures over the current integrity-chain head and run provenance.

The repository must contain **only public verification material**. Private keys must never be committed, uploaded as workflow artifacts, printed in logs, or stored in generated reports.

## Authority files

`keys/keyring.json` is the key authority registry.

When signing is provisioned it must contain exactly one `active` key. Retired keys remain listed so historical signatures remain verifiable. Every key row records its `keyId`, public-key path and SHA-256 fingerprint.

`keys/x1-epg-ed25519-public.pem` is the runtime signing-key alias. Its fingerprint must exactly match the active key in `keyring.json`.

The actual public key should also remain under a stable versioned path such as:

`keys/x1-epg-ed25519-2026-01.pem`

The private key is supplied only through the GitHub Actions secret:

`X1_EPG_ED25519_PRIVATE_KEY_PEM`

## First provisioning

Generate the key pair on a trusted administrator workstation, not in GitHub Actions:

```bash
openssl genpkey -algorithm ED25519 -out x1-epg-ed25519-private.pem
openssl pkey -in x1-epg-ed25519-private.pem -pubout -out x1-epg-ed25519-2026-01.pem
cp x1-epg-ed25519-2026-01.pem x1-epg-ed25519-public.pem
```

Then:

1. Store the private PEM in the approved X1 secret-management process.
2. Configure its complete contents as `X1_EPG_ED25519_PRIVATE_KEY_PEM`.
3. Commit the versioned public key and the alias only.
4. Add the public-key SHA-256 fingerprint to `keys/keyring.json` and mark that key `active`.
5. Add an explicit initial transition record with `fromKeyId: null`.
6. Run `python tools/key_rotation.py verify-signing-key`.
7. Run `python tools/signed_provenance.py status`.

## Rotation

Rotation is explicit and preserves the old public key permanently for historical verification.

A rotation must:

1. Add the new versioned public key under `keys/`.
2. Keep the old public key file.
3. Mark the previous key `retired` in `keyring.json`.
4. Add the new key as the only `active` key.
5. Add a transition record containing old key ID, new key ID, effective time, approver and reason.
6. Replace only the alias `keys/x1-epg-ed25519-public.pem` with the new active public key.
7. Replace the private GitHub secret with the matching new private key.
8. Run `python tools/key_rotation.py verify-signing-key` before allowing signing.

Silently replacing a public key without a keyring transition is forbidden.

## External anchor

P6.10 can bind a signed integrity head to an external transparency/immutability service. The repository never assumes that an external service exists merely because the anchor code is present.

Optional secrets/configuration:

`X1_EPG_EXTERNAL_ANCHOR_URL`

`X1_EPG_EXTERNAL_ANCHOR_TOKEN`

Both must be configured together. A successful service must return JSON containing the submitted `anchorSha256`, an `immutableId`, and `anchoredAt`. The receipt is stored in `data/external-anchor-receipt.json`.

The request itself is stored in `data/external-anchor-request.json` and can be independently hashed and verified.

## Verification

```bash
python tools/key_rotation.py verify
python tools/key_rotation.py verify-signing-key
python tools/signed_provenance.py verify
python tools/external_anchor.py verify
```

A signature proves that the configured X1 signing key signed the canonical integrity-head/provenance payload. An external anchor receipt proves only that an external service acknowledged the exact anchor hash. Neither grants source licensing, source quality, availability, or production correctness.
