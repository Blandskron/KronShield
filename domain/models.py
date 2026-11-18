from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict


class FindingType(str, Enum):
    """
    Enumeration of supported finding types.

    - INFO: General information (e.g., HTTP status, headers)
    - PORT: Open port detected
    - XSS: Cross-Site Scripting indicator
    - SQLI: SQL Injection indicator
    - ERROR: Execution or network error during testing
    """
    INFO = "info"
    PORT = "port"
    XSS = "xss"
    SQLI = "sqli"
    ERROR = "error"


class FindingStatus(str, Enum):
    OBSERVED = "observed"
    SUSPECTED = "suspected"
    INCONCLUSIVE = "inconclusive"


class FindingConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"


@dataclass
class Finding:
    """
    Represents a security finding from any audit stage.

    Attributes:
        type (FindingType): The category of the finding.
        detail (str): Description of the finding.
        url (Optional[str]): Target URL where the issue was detected.
        payload (Optional[str]): Payload used to trigger the behavior (if applicable).
        extra (Optional[Dict]): Additional metadata (headers, port info, etc).
        status: Classification when the check distinguishes evidence levels.
        confidence: Strength of that classification, when available.
    """
    type: FindingType
    detail: str
    url: Optional[str] = None
    payload: Optional[str] = None
    extra: Optional[Dict] = None
    status: FindingStatus | None = None
    confidence: FindingConfidence | None = None
