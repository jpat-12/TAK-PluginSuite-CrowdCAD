# Guides

| Guide | For | Markdown | PDF |
|---|---|---|---|
| **Setup Guide** | The infra-TAK operator: install, connect, verify, pre-event checklist | [SETUP_GUIDE.md](SETUP_GUIDE.md) | [SETUP_GUIDE.pdf](SETUP_GUIDE.pdf) |
| **User Guide** | Medics (ATAK), dispatchers (CloudTAK), command staff and EOC (CloudTAK/WebTAK) | [USER_GUIDE.md](USER_GUIDE.md) | [USER_GUIDE.pdf](USER_GUIDE.pdf) |

Per-component install reference (bridge, CrowdCAD, ATAK, CloudTAK, WebTAK, how they connect):
[../docs/install/](../docs/install/README.md).

[SCREENSHOTS.md](SCREENSHOTS.md) is the shot list for replacing the mockups with real screenshots.

Images are mockups drawn from the UI code (`images/` here, plus the README's in `../docs/images/`),
not screenshots.

**Rebuild the PDFs** after editing the Markdown (needs pandoc and Node with Playwright + Chromium):

```bash
bash guides/build_pdfs.sh
```
