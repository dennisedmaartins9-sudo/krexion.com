# Krexion Windows Installer — Code Signing (Permanent Smart App Control Fix)

Windows 11 **Smart App Control (SAC)** blocks unsigned files extracted during install
(`Error 4551: Application Control policy has blocked this file`).

The **permanent fix** is to sign every customer-facing `.exe` in CI before publishing
`Krexion-Setup-vX.Y.Z.exe`. After credentials are configured once, **users do nothing**.

---

## Recommended: EV/OV certificate as PFX (GitHub Secrets)

1. Purchase **Code Signing** certificate (EV preferred for instant SAC reputation):
   - DigiCert, Sectigo, SSL.com (~$300–500/year EV)
2. Export as `.pfx` with private key.
3. Base64-encode the PFX (PowerShell):

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\path\krexion-codesign.pfx')) | Set-Clipboard
```

4. Add **GitHub repo secrets** (Settings → Secrets → Actions):

| Secret | Value |
|--------|--------|
| `KREXION_CODESIGN_PFX_BASE64` | pasted base64 |
| `KREXION_CODESIGN_PFX_PASSWORD` | PFX export password |

5. Push a `backend/VERSION` bump — native workflow signs automatically.

---

## Alternative: Certificate on self-hosted Windows runner

If the cert is installed in `LocalMachine\My` on `krexion-windows` runner:

```powershell
Get-ChildItem Cert:\LocalMachine\My -CodeSigningCert | Format-List Subject, Thumbprint, NotAfter
```

Add secret:

| Secret | Value |
|--------|--------|
| `KREXION_CODESIGN_THUMBPRINT` | SHA1 thumbprint (no spaces) |

---

## Alternative: Azure Artifact Signing (~$10/month)

1. Create [Azure Artifact Signing](https://azure.microsoft.com/products/artifact-signing) account + profile.
2. Install signing dlib on runner (once):

```powershell
dotnet tool install --global sign
# Follow Azure docs to download Azure.CodeSigning.Dlib.dll to C:\krexion-ci-cache\
```

3. GitHub secrets: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`,
   plus `AZURE_CODESIGN_METADATA_JSON` (metadata.json contents for your profile).

---

## Verify a signed build

```powershell
Get-AuthenticodeSignature '.\Krexion-Setup-v2.7.66.exe' | Format-List *
```

Status must be **Valid**. Publisher should show your company name.

---

## What gets signed in CI

- `krexion-core.exe` + bundled Python tools under `krexion-backend.dist`
- `mongod.exe`, `krexion-service.exe` (NSSM)
- Playwright browser `.exe` files (only if not already Valid-signed)
- Final `Krexion-Setup-vX.Y.Z.exe`

Microsoft redistributables (`vc_redist`, WebView2 bootstrapper) are already signed — skipped.
