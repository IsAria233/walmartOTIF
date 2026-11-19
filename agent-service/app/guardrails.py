"""Detect explicit instructions embedded in untrusted OTIF input."""

import re
import unicodedata

UNTRUSTED_INSTRUCTIONS = "Untrusted instructions detected in evidence"

# Match instructions to the workflow. Ordinary supplier requests to review or
# waive a fine are part of the evidence and do not match this rule.
INSTRUCTION = re.compile(
    r"\b(?:system|developer)\s+(?:note|message|instruction)s?\s*:"
    r"|(?:\[|<)\s*(?:system|developer)\s*(?:\]|>)"
    r"|\b(?:ignore|disregard|override)\s+(?:all\s+|the\s+)?"
    r"(?:(?:previous|prior|above|system|developer|original)\s+)+(?:instructions?|rules?|prompts?)\b"
    r"|(?:^|[.;!:?]\s*|\band\s+)(?:please\s+)?(?:skip|bypass)\s+"
    r"(?:the\s+)?(?:(?:manual|human|manager)\s+)?(?:review|approvals?)\b"
    r"|\b(?:reveal|print|show)\s+(?:the\s+|your\s+)?(?:system|developer)\s+prompt\b"
)


class PromptInjectionDetected(Exception):
    """An untrusted record contains a suspected instruction to the workflow."""


def contains_instruction(value: object) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            text = unicodedata.normalize("NFKC", item).casefold()
            text = "".join(character for character in text if unicodedata.category(character) != "Cf")
            if INSTRUCTION.search(" ".join(text.split())) is not None:
                return True
        elif isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
    return False
