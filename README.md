# Open Terminal · Ivy Bridge AVX1

[English](README.md) · [Русский](README.ru.md)

Experimental builds for personal compatibility and performance testing. Upstream application names and interface branding are retained.

[Upstream project](https://github.com/open-webui/open-terminal) · [Packages](https://github.com/aktalascloud/open-terminal-ivybridge-avx1/releases)

Download the single latest package, extract it and run `Install.cmd`. `Install.cmd -CheckOnly` verifies integrity without installing. Packages exclude personal configuration, credentials, history, caches and model weights. Models download from Hugging Face on demand.

One build combines current official source and reviewed fork patches. There are no separate stable/dev downloads.

Extended Russian UI and menu translation; interpolation parameters are checked in every build.

## Patches

| ID | Change | Source |
|---|---|---|
| TERM-001 | Strip inherited OPEN_TERMINAL_* credentials from shells, execution and notebook kernels; preserve application environment. | [PR](https://github.com/open-webui/open-terminal/pull/128) |
| TERM-002 | Do not pass host/port to FastMCP stdio transport. | [PR](https://github.com/open-webui/open-terminal/pull/120) |
| TERM-003 | Pin shared API/runtime dependencies to the tested Open WebUI-compatible versions; avoid upgrading its FastAPI/Pydantic during Terminal installation. | `.avx1/PATCHES.json` |

## Measurements

| Metric | Verified improvement |
|---|---|
| LLM generation throughput | Not measured |
| JSON on Ivy Bridge | Pending stock/optimized comparison |
| Android runtime performance | Not measured on a physical phone |

Unmeasured changes have no claimed percentage. JSON timings cover serialization/parsing, not tokens/s. LTO and ISA flags apply only to the named native components; they do not turn Python or TypeScript into native code. AVX2/FMA and fast-math are not enabled.

## Licensing and compatibility

Original licenses, notices and license history are preserved. Each binary package includes its corresponding source. Private signing keys stay outside the repository. APKs use a separate application ID.

Local deployment additionally checks the owner's private filter and Telegram bridge. Their source, settings and data are not published. Unreviewed PR/fork changes remain candidates; accepted upstream fixes arrive through merges of official branches.
