# Applied downstream patches: terminal

Only currently applied maintainer differences from the exact official baseline are included.
Содержит только текущие применённые нами отличия от указанного официального upstream.
Mainstream-only commits, rejected proposals and reverted experiments are excluded.
Коммиты самого mainstream, неприменённые предложения и отменённые эксперименты исключены.

Official baseline: `47fbd8f0f6ee632dc91500ece877a40b64014941`. Downstream snapshot: `da1a3b08d27d56f2a3805103828fe789600aa9ab`.
Patches are already applied in this fork. Apply `series` only to a clean checkout of that exact baseline.
В этом форке патчи уже применены. `series` предназначен только для чистого checkout указанной базы.
Apply the numbered patches in the order listed in `series`. Each row describes one topic.
Накладывайте патчи в порядке файла `series`. Изменения в общих файлах остаются вместе.
The manifest records each patch’s exact file list and SHA256.

Credential and OS-user identity isolation, managed authenticated readiness, bounded Unicode-aware search, and non-mutating-by-default Cline discovery.

| Order | Patch | Description | Files |
|---:|---|---|---:|
| 1 | [01-credential-isolation.patch](01-credential-isolation.patch) | Remove host Git and SSH credentials from other OS users and require Cline discovery opt-in / Изолирует ключи Git и SSH между пользователями ОС и требует явного включения поиска Cline. | 7 |
| 2 | [02-bounded-search.patch](02-bounded-search.patch) | Limit filesystem traversal and keep Unicode search previews bounded / Ограничивает обход файлов и размер Unicode-фрагментов поиска. | 5 |
| 3 | [03-document-comparison.patch](03-document-comparison.patch) | Extract text from office documents and compare files / Извлекает текст из офисных документов и сравнивает файлы. | 2 |
| 4 | [04-chrome-proxy.patch](04-chrome-proxy.patch) | Adapt the Chrome proxy and verify browser access contracts / Адаптирует прокси Chrome и проверяет правила доступа к браузеру. | 2 |
| 5 | [05-skills-paths.patch](05-skills-paths.patch) | Normalize skill metadata and resource paths / Нормализует метаданные навыков и пути к их ресурсам. | 1 |
| 6 | [06-service-api.patch](06-service-api.patch) | Provide authenticated readiness, CLI CORS, MCP startup and bounded process log delivery / Добавляет проверку готовности с авторизацией, CORS для CLI, запуск MCP и ограниченную выдачу логов. | 14 |
| 7 | [07-localization-checks.patch](07-localization-checks.patch) | Check localization coverage in the portable package / Проверяет полноту переводов в переносимом пакете. | 1 |
| 8 | [08-package-runtime.patch](08-package-runtime.patch) | Set Terminal package dependencies and container entry points / Настраивает зависимости Terminal и команды запуска контейнера. | 5 |
| 9 | [09-portable-install.patch](09-portable-install.patch) | Provide portable build commands and the fork installer / Добавляет команды переносимой сборки и установщик. | 4 |
| 10 | [10-ci-build.patch](10-ci-build.patch) | Pin toolchains and package inputs, and run the fork build and publication checks / Закрепляет инструменты и входы сборки, запускает проверки пакетов и публикации. | 11 |
| 11 | [11-project-docs.patch](11-project-docs.patch) | Document fork setup, support and license terms / Описывает установку, поддержку и условия лицензирования форка. | 4 |
| 12 | [12-fork-records.patch](12-fork-records.patch) | Record fork changes, upstream reviews and qualification measurements / Хранит журнал изменений, разбор upstream и результаты проверок. | 2 |
