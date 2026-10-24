"""Bound grep tool output without hiding matches in long legitimate text lines."""
MAX_MATCH_CONTENT = 300

def bounded_match_content(line: str, match_start: int) -> str:
    if len(line) <= MAX_MATCH_CONTENT:
        return line.rstrip("\r\n")
    # Avoid copying an entire multi-megabyte matching line just to trim its EOL.
    length = len(line)
    while length and line[length - 1] in "\r\n":
        length -= 1
    if length <= MAX_MATCH_CONTENT:
        return line[:length]
    # Adapted from the context-overflow problem in upstream PR #144. Preserve
    # long JSON/minified-code matches and show the actual matching region.
    left = max(0, match_start - MAX_MATCH_CONTENT // 3)
    right = min(length, left + MAX_MATCH_CONTENT)
    left = max(0, right - MAX_MATCH_CONTENT)
    return (("…" if left else "") + line[left:right] + ("…" if right < length else "")
            + f" [truncated; columns {left + 1}-{right} of {length}]")
