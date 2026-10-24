"""Bound grep tool output without hiding matches in long legitimate text lines."""
MAX_MATCH_CONTENT = 300

def bounded_match_content(line: str, match_start: int) -> str:
    content = line.rstrip("\r\n")
    if len(content) <= MAX_MATCH_CONTENT:
        return content
    # Adapted from the context-overflow problem in upstream PR #144. Preserve
    # long JSON/minified-code matches and show the actual matching region.
    left = max(0, match_start - MAX_MATCH_CONTENT // 3)
    right = min(len(content), left + MAX_MATCH_CONTENT)
    left = max(0, right - MAX_MATCH_CONTENT)
    return (("…" if left else "") + content[left:right] + ("…" if right < len(content) else "")
            + f" [truncated; columns {left + 1}-{right} of {len(content)}]")
