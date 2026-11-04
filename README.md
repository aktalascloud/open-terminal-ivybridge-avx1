# Open Terminal AVX1

[Русский](README.ru.md)

Unofficial fork with reviewed agent/MCP fixes and extended Russian UI. One latest ZIP + Install.cmd.

[Upstream](https://github.com/open-webui/open-terminal) · [Release](https://github.com/aktalascloud/open-terminal-ivybridge-avx1/releases/latest) · [Patches](.avx1/PATCHES.json)

Official0.16.1 avoids recursive filesystem watches outside Git repositories while retaining Git/worktree metadata watches. Authenticated readiness and independent managed startup are preserved.

## Build

Requires Python 3.12+, Git and GitHub CLI for CI. No LLM, model weights or Codex dependency.

```cmd
Build.cmd status
Build.cmd build
```

`build` verifies the clean published commit and dispatches the pinned workflow. For a prepared local compiler/SDK environment: `Build.cmd local`. Dependencies, flags, tests and license gates are in `.avx1/`; lockfiles and source history are retained. Signing keys stay outside the repository.

## Run and verify

Mainstream 0.16 adds owned browser sessions, filesystem/port/process events and desktop APIs. Capture and input start only on an authenticated API/tool request; native Windows/macOS use the signed-in desktop shared across workspaces. Windows CDP stays on loopback without a network proxy. Search does not open device/FIFO/socket files or cross mounts; an explicitly selected mount remains searchable.

Content-match previews retain original UTF-16 columns; the 1 MiB content-search cap also applies with ripgrep. Oversized files can still match by name. This is not a global response-byte budget.

Proxy mode rewrites page content; use managed Chrome for sign-ins and sites that need browser origin isolation.

`run` honors CORS from CLI, environment and TOML in that order. `mcp --api-key` explicitly overrides the existing environment/secret-file/config sources; stdio receives no network arguments.

Use the single release package. Keep user data separate from source. Settings, endpoints and model selection are runtime configuration, not build requirements. Ivy Bridge: AVX/F16C, O3 and verified LTO, without AVX2/FMA/PGO/fast-math. Actual native flags and prebuilt components are identified in the manifest.

Current checks and measurements: [.avx1/measurements/latest.json](.avx1/measurements/latest.json). CPU microbenchmarks are not LLM tokens/s. Original licenses and notices apply.
