# Open Terminal · Ivy Bridge AVX1

[English](README.md) · [Русский](README.ru.md) · [Исходный проект](https://github.com/open-webui/open-terminal) · [Релизы](https://github.com/aktalascloud/open-terminal-ivybridge-avx1/releases/latest)

Terminal/MCP backend для Windows. Русский интерфейс доступен через WebUI/Desktop.

Скачайте последний ZIP, распакуйте и запустите `Install.cmd`.

## Изменения

- Компактный grep без потери совпадений в длинных строках: адаптация [#144](https://github.com/open-webui/open-terminal/pull/144).
- Наш новый preview не копирует всю строку.
- Изоляция ключей, MCP stdio и совместимые с WebUI зависимости. [Все патчи](.avx1/PATCHES.json).

## Проверки и замеры

На настоящем Xeon E5-2697 v2 новый preview снизил CPU-затраты авторизованного grep API на **9,20–13,18%** относительно прошлого релиза форка в двух независимых прогонах. Создание preview отдельно потребовало на **99,73% меньше CPU-времени**. Вывод совпал в 108 проверках Unicode/окончаний строк на прогон. Вход: одна синтетическая строка JSON на 2 МБ. Результат не переносится на малые файлы или tokens/s LLM. [Замеры и методика](.avx1/measurements/grep-cpu-20261024.json) · [Повторить](.avx1/bench_search_cpu.py).

Оригинальные лицензии, уведомления и история исходников сохранены. Точные исходники указаны в релизе. Ключи, логи, модели LLM и закрытый код фильтра/бриджа в публичные пакеты не входят.
