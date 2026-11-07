# Applied downstream patches: terminal

Only currently applied maintainer differences from the exact official baseline are included.
Содержит только текущие применённые нами отличия от указанного официального upstream.
Mainstream-only commits, rejected proposals and reverted experiments are excluded.
Коммиты самого mainstream, неприменённые предложения и отменённые эксперименты исключены.

Official baseline: `2d22dc9a1b5b121f189be7a3c1bcaba9d677b491`. Downstream snapshot: `896c7841e824b481d428b228168eaf65f9c0ff83`.
Patches are already applied in this fork. Apply `series` only to a clean checkout of that exact baseline.
В этом форке патчи уже применены. `series` предназначен только для чистого checkout указанной базы.
Files are grouped by purpose; manifest.json records paths, hashes and the exact reconstructed tree.

Credential and OS-user identity isolation, managed authenticated readiness, bounded Unicode-aware search, and non-mutating-by-default Cline discovery.

| Patch | Description | Files |
|---|---|---|
| [01-runtime.patch](01-runtime.patch) | Local runtime, integration, security, dependency and platform adaptations / Наши изменения работы, интеграций, безопасности и платформ. | 24 |
| [02-build.patch](02-build.patch) | Our reproducible build, toolchain and CI recipes / Наши сборочные рецепты, toolchain и CI. | 16 |
| [03-tests.patch](03-tests.patch) | Our regressions and adaptations of upstream fixtures / Наши регрессии и адаптации тестов. | 12 |
| [04-documentation.patch](04-documentation.patch) | Our fork documentation, notices and qualification evidence / Наши описания форка, уведомления и доказательства квалификации. | 6 |
