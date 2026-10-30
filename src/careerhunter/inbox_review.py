"""Privacy-first, offline classification of saved recruitment emails.

No Gmail credentials, scraping, sending or automatic CRM state changes.
Treat every signal as an unverified suggestion for owner review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import Iterable

MAX_EMAIL_BYTES = 1_000_000
MAX_MESSAGES = 500
ROOT = Path(__file__).resolve().parents[2]
_CUT = re.compile(
    r"(?im)^(?:on .{1,160}wrote:|[- ]{2,}original message[- ]{2,}|from:\s.{2,150}$)"
)
_SIGNALS = (
    ("interview", re.compile(r"\b(?:interview invitation|schedule (?:an?|your) interview|"
                              r"interview availability|mülakat daveti|görüşmeye davet)\b", re.I)),
    ("assessment", re.compile(r"\b(?:coding assessment|take.home assessment|technical test|"
                               r"online assessment|teknik değerlendirme)\b", re.I)),
    ("rejection", re.compile(r"\b(?:not moving forward|unfortunately.*(?:position|application)|"
                              r"decided not to proceed|başvurunuz olumsuz|"
                              r"olumsuz değerlendirilmiştir)\b", re.I)),
)


@dataclass(frozen=True)
class InboxSignal:
    id_hash: str
    proposed_category: str
    needs_review: bool = True


def _body(message: EmailMessage) -> str:
    """Only short plain text; never read attachment content."""
    if message.is_multipart():
        parts = message.walk()
    else:
        parts = (message,)
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        if part.get_content_type() != "text/plain":
            continue
        try:
            content = part.get_content()
        except (UnicodeError, LookupError, ValueError, TypeError):
            continue
        if isinstance(content, str):
            return content[:12000]
    return ""


def classify_eml(payload: bytes) -> InboxSignal:
    if len(payload) > MAX_EMAIL_BYTES:
        raise ValueError("Email exceeds safe offline size limit")
    try:
        parsed = BytesParser(policy=policy.default).parsebytes(payload)
        subject = str(parsed.get("Subject", ""))[:250]
        message_id = str(parsed.get("Message-ID", ""))[:250].strip()
        if not message_id:
            message_id = hashlib.sha256(payload).hexdigest()
        head = _CUT.split(_body(parsed), maxsplit=1)[0][:4000]
        text = subject + "\n" + head
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ValueError("Invalid email") from exc
    categories = [name for name, pattern in _SIGNALS if pattern.search(text)]
    # Mixed or quoted recruiter content must not trigger an automatic decision.
    category = categories[0] if len(categories) == 1 else "needs_review"
    return InboxSignal(
        id_hash=hashlib.sha256(message_id.encode("utf-8")).hexdigest(),
        proposed_category=category,
    )


def analyze_eml_directory(folder: Path) -> list[InboxSignal]:
    folder = folder.resolve()
    if not folder.is_dir() or folder.is_relative_to(ROOT):
        raise ValueError("Emails must be in an existing private directory outside repo")
    output = []
    seen = set()
    paths = sorted(folder.glob("*.eml"))
    if len(paths) > MAX_MESSAGES:
        raise ValueError("Too many emails; use a bounded batch")
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Symbolic links and non-files are not accepted")
        if path.stat().st_size > MAX_EMAIL_BYTES:
            raise ValueError("Email exceeds safe offline size limit")
        signal = classify_eml(path.read_bytes())
        if signal.id_hash not in seen:
            output.append(signal)
            seen.add(signal.id_hash)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify private .eml files; never send emails")
    parser.add_argument("--eml-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    output_path = args.output.resolve()
    if output_path.is_relative_to(ROOT) or output_path.suffix.lower() != ".json":
        parser.error("JSON output must be outside public repository")
    if not output_path.parent.is_dir():
        parser.error("Output parent directory does not exist")
    try:
        signals = analyze_eml_directory(args.eml_dir)
        output_path.write_text(
            json.dumps([asdict(item) for item in signals], indent=2), encoding="utf-8"
        )
        print(f"Saved {len(signals)} proposed recruitment classifications for owner review")
        return 0
    except (ValueError, OSError) as exc:
        print(f"FAIL: safe mail review: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
