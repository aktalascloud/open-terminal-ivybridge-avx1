# Open Terminal · Ivy Bridge AVX1

[English](README.md) · [Русский](README.ru.md) · [Upstream](https://github.com/open-webui/open-terminal) · [Releases](https://github.com/aktalascloud/open-terminal-ivybridge-avx1/releases/latest)

Terminal/MCP backend for Windows. Russian UI comes through WebUI/Desktop.

Download the latest ZIP, extract it and run `Install.cmd`.

## Changes

- Bounded grep without losing long-line matches: adapted [#144](https://github.com/open-webui/open-terminal/pull/144).
- Our new preview avoids copying the whole line.
- Credential isolation, MCP stdio and compatible WebUI dependencies. [Full patch list](.avx1/PATCHES.json).

## Evidence

On an actual Xeon E5-2697 v2, the new preview reduced authenticated grep API CPU cost by **9.20–13.18%** versus the previous fork release in two independent runs. Preview construction alone used **99.73% less CPU time**. Outputs match in 108 Unicode/EOL cases per run. Fixture: one synthetic 2 MB JSON line. Small-file performance and LLM tokens/s are not inferred. [Samples and method](.avx1/measurements/grep-cpu-20261024.json) · [Reproduce](.avx1/bench_search_cpu.py).

Original licenses/notices and source history are preserved. Exact corresponding source is linked from each release. Credentials, logs, models and private filter/bridge code stay outside the public packages.
