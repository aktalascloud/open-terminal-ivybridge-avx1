"""Read-only text comparison. Workers receive structured input on stdin."""

import difflib
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import sys

from open_terminal.utils.limits import run_worker

from fastapi import HTTPException
from pydantic import BaseModel, Field

from open_terminal.utils.documents import (
    EXTRACTORS,
    extract_docx,
    extract_pdf,
    extract_epub,
)

TIMEOUT_SECONDS = 60
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_LINES = 50_000


class ComparisonText(io.StringIO):
    def write(self, text):
        # CRLF normalization can halve the length; enforce the exact limit below.
        if self.tell() + len(text) > 2 * MAX_TEXT_CHARS:
            raise ValueError("Extracted text exceeds the comparison limit (2 million characters / 50,000 lines). Nothing was truncated.")
        return super().write(text)


class CompareRequest(BaseModel):
    original: str = Field(min_length=1)
    revised: str = Field(min_length=1)
    ignore_whitespace: bool = False


def extract(path):
    name = Path(path).name
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            raise ValueError("File exceeds the 50 MiB comparison limit.")
        mime = mimetypes.guess_type(path)[0]
        notices = []
        extractor = next(
            (
                fn
                for kind, suffix, fn in EXTRACTORS
                if (kind and kind == mime) or (suffix and path.lower().endswith(suffix))
            ),
            None,
        )
        if extractor:
            if hasattr(extractor, "write_to"):
                output = ComparisonText()
                options = {"strict": True} if extractor in (extract_pdf, extract_epub) else {}
                extractor.write_to(path, output, **options)
                text = output.getvalue()
            elif extractor in (extract_pdf, extract_epub):
                text = extractor(path, strict=True)
            else:
                text = extractor(path)
            notices.append("Text only; formatting, images and layout are not compared.")
            if extractor == extract_docx:
                notices.append(
                    "Headers, footers, comments, footnotes and text boxes are excluded. "
                    "Tracked insertions are included; tracked deletions are excluded."
                )
            if path.lower().endswith((".xlsx", ".xls", ".ods")):
                notices.append(
                    "Compares extracted cell values; formulas and formatting are not compared."
                )
            if path.lower().endswith((".pptx", ".odp")):
                notices.append(
                    "Compares extracted slide text; speaker notes and embedded objects are excluded."
                )
            if path.lower().endswith(".pptx"):
                notices.append("Tables and grouped shapes are excluded.")
            if path.lower().endswith(".eml"):
                notices.append(
                    "Compares message headers and body; attachments are excluded."
                )
            if not text.strip():
                raise ValueError(
                    "No extractable text. This document cannot be compared."
                )
        else:
            raw = Path(path).read_bytes()
            encoding = "utf-8-sig"
            if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
                encoding = "utf-32"
            elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                encoding = "utf-16"
            try:
                text = raw.decode(encoding)
            except UnicodeDecodeError as exc:
                raise ValueError("Unsupported binary file or text encoding.") from exc
            if any(ord(c) < 32 and c not in "\n\r\t\f" for c in text):
                raise ValueError("Unsupported binary file.")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError("Extracted text exceeds the comparison limit (2 million characters / 50,000 lines). Nothing was truncated.")
        line_breaks = "\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"
        line_count = sum(1 for _ in re.finditer("[" + line_breaks + "]", text)) + bool(text and text[-1] not in line_breaks)
        if line_count > MAX_LINES:
            raise ValueError(
                "Extracted text exceeds the comparison limit (2 million characters / 50,000 lines). Nothing was truncated."
            )
        lines = text.splitlines()
        return {"path": path, "name": name, "notices": notices}, lines
    except Exception as exc:
        raise ValueError(f"{name}: {exc}") from exc


def segments(original, revised):
    # Bound expensive intraline matching; whole lines remain visible above this limit.
    if max(len(original), len(revised)) > 4096:
        return (
            [{"text": original, "changed": False}],
            [{"text": revised, "changed": False}],
        )
    a, b = (re.findall(r"\w+|[^\w\s]|\s+", text) for text in (original, revised))
    left, right = [], []
    for tag, i, j, k, l in difflib.SequenceMatcher(
        None, a, b, autojunk=False
    ).get_opcodes():
        if i != j:
            left.append({"text": "".join(a[i:j]), "changed": tag != "equal"})
        if k != l:
            right.append({"text": "".join(b[k:l]), "changed": tag != "equal"})
    return left, right


def compare(original, revised, ignore_whitespace=False):
    old, a = extract(original)
    new, b = extract(revised)
    keys = lambda lines: (
        [re.sub(r"\s+", "", line) for line in lines] if ignore_whitespace else lines
    )
    matcher = difflib.SequenceMatcher(None, keys(a), keys(b), autojunk=False)
    hunks, additions, deletions = [], 0, 0
    for group in matcher.get_grouped_opcodes(3):
        lines = []
        for tag, i, j, k, l in group:
            if tag == "equal":
                for x, y in zip(range(i, j), range(k, l)):
                    lines.append(
                        {
                            "type": "context",
                            "oldNumber": x + 1,
                            "newNumber": y + 1,
                            "content": a[x],
                            "revisedContent": b[y],
                            "segments": [{"text": a[x], "changed": False}],
                        }
                    )
                continue
            removed, added = [], []
            for x in range(i, j):
                removed.append(
                    {
                        "type": "removed",
                        "oldNumber": x + 1,
                        "newNumber": None,
                        "content": a[x],
                        "segments": [{"text": a[x], "changed": False}],
                    }
                )
            for y in range(k, l):
                added.append(
                    {
                        "type": "added",
                        "oldNumber": None,
                        "newNumber": y + 1,
                        "content": b[y],
                        "segments": [{"text": b[y], "changed": False}],
                    }
                )
            for left, right in zip(removed, added):
                left["segments"], right["segments"] = segments(
                    left["content"], right["content"]
                )
            lines.extend(removed + added)
            additions += len(added)
            deletions += len(removed)
        _, i, _, k, _ = group[0]
        _, _, j, _, l = group[-1]
        old_start = i + 1 if j > i else i
        new_start = k + 1 if l > k else k
        hunks.append(
            {"header": f"@@ -{old_start},{j-i} +{new_start},{l-k} @@", "lines": lines}
        )
    return {
        "original": old,
        "revised": new,
        "additions": additions,
        "deletions": deletions,
        "hunks": hunks,
    }


async def run_comparison(request, payload, fs, cwd=None):
    paths = []
    for path in (payload.original, payload.revised):
        target = fs.resolve_path(path, cwd=cwd)
        try:
            fs._check_path(target)
            target = os.path.realpath(target)
            fs._check_path(target)
            if not await fs.isfile(target):
                raise HTTPException(404, f"{Path(path).name}: File not found.")
        except PermissionError as exc:
            raise HTTPException(403, f"{Path(path).name}: Access denied.") from exc
        paths.append(target)
    command = [sys.executable, "-m", "open_terminal.utils.file_compare"]
    process_options = {}
    if fs.username:
        if hasattr(os, "getuid") and os.getuid() == 0:
            import pwd

            account = pwd.getpwnam(fs.username)
            process_options = {
                "user": account.pw_uid,
                "group": account.pw_gid,
                "extra_groups": [],
            }
        else:
            command = ["sudo", "-n", "-u", fs.username, "--", *command]
    try:
        stdout = await run_worker(
            command,
            json.dumps({"original": paths[0], "revised": paths[1], "ignore_whitespace": payload.ignore_whitespace}).encode(),
            request=request, timeout=TIMEOUT_SECONDS, **process_options,
        )
    except HTTPException as exc:
        messages = {
            408: "Comparison exceeded the 60 second limit. Try smaller files.",
            422: "Comparison failed. Check that the document libraries are installed and the files are readable.",
            499: "Comparison cancelled.",
        }
        raise HTTPException(exc.status_code, messages.get(exc.status_code, exc.detail)) from exc
    result = json.loads(stdout)
    if "error" in result:
        raise HTTPException(422, result["error"])
    return result


if __name__ == "__main__":
    try:
        result = compare(**json.load(sys.stdin))
    except Exception as exc:
        result = {"error": str(exc)}
    json.dump(result, sys.stdout)
