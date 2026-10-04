"""`.pdf`: `pypdf` (BSD-3-Clause, pinned in pyproject.toml). Page texts joined by a blank
line. An encrypted PDF is read only when its user password is empty. No OCR: a scanned PDF
has no text layer and ends `no_text`."""

import io

import pypdf
from pypdf.errors import PdfReadError

from app.modules.intake.domain.parsing import ParseError, ParseErrorCode

NAME = f"pypdf@{pypdf.__version__}"


def parse(data: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ParseError(ParseErrorCode.UNREADABLE)
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except ParseError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, AttributeError, IndexError, OSError):
        raise ParseError(ParseErrorCode.UNREADABLE) from None
