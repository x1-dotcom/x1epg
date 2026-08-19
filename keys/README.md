# X1 EPG signing keys

P6.9 adds Ed25519 signatures over the current X1 EPG integrity-chain head and run provenance.

The repository must contain **only** the public verification key:

`keys/x1-epg-ed25519-public.pem`

The private key must never be committed, uploaded as an artifact, printed in logs, or stored in any generated report. Runtime signing expects the PEM private key through the GitHub Actions secret:

`X1_EPG_ED25519_PRIVATE_KEY_PEM`

## Provisioning

Generate the key pair on a trusted administrator workstation, not in GitHub Actions:

```bash
openssl genpkey -algorithm ED25519 -out x1-epg-ed25519-private.pem
openssl pkey -in x1-epg-ed25519-private.pem -pubout -out x1-epg-ed25519-public.pem
```

1. Store `x1-epg-ed25519-private.pem` in the approved X1 secret-management process.
2. Configure its complete PEM contents as the GitHub Actions secret `X1_EPG_ED25519_PRIVATE_KEY_PEM`.
3. Commit only `x1-epg-ed25519-public.pem` at `keys/x1-epg-ed25519-public.pem`.
4. Run `python tools/signed_provenance.py status`.
5. A runtime sync may sign only when the private secret is present and its derived public key fingerprint exactly matches the committed public key.

## Verification

After a signed runtime execution:

```bash
python tools/signed_provenance.py verify
```

Verification is fail-closed for a missing/malformed signature, a changed integrity head, changed provenance, a mismatched public-key fingerprint, or an invalid Ed25519 signature.

## Rotation

Key rotation must be explicit. Never silently replace the public key while retaining old signed-head claims as if they used the new key. A future rotation procedure should record the old and new public-key fingerprints and an operator-approved transition record.

A signature proves that the configured X1 signing key signed the canonical integrity-head/provenance payload. It does not prove source licensing, source quality, availability, or production correctness.
