# Open Terminal AVX1

[Русский](README.ru.md)

Unofficial fork with reviewed agent/MCP fixes and extended Russian UI. One latest ZIP + Install.cmd.

[Upstream](https://github.com/open-webui/open-terminal) · [Release](https://github.com/aktalascloud/open-terminal-ivybridge-avx1/releases/latest) · [Patches](.avx1/PATCHES.json)

## Build

Requires Python 3.12+, Git and GitHub CLI for CI. No LLM, model weights or Codex dependency.

```cmd
Build.cmd status
Build.cmd build
```

`build` verifies the clean published commit and dispatches the pinned workflow. For a prepared local compiler/SDK environment: `Build.cmd local`. Dependencies, flags, tests and license gates are in `.avx1/`; lockfiles and source history are retained. Signing keys stay outside the repository.

## Run and verify

Use the single release package. Keep user data separate from source. Settings, endpoints and model selection are runtime configuration, not build requirements. Ivy Bridge: AVX/F16C, O3 and verified LTO, without AVX2/FMA/PGO/fast-math. Actual native flags and prebuilt components are identified in the manifest.

Current checks and measurements: [.avx1/measurements/latest.json](.avx1/measurements/latest.json). CPU microbenchmarks are not LLM tokens/s. Original licenses and notices apply.
