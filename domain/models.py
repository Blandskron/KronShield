from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict

class FindingType(str, Enum):
    """
    Enumeration of supported finding types.

    - INFO: General information (e.g., HTTP status, headers)
    - PORT: Open port detected
    - XSS: Cross-Site Scripting vulnerability
    - SQLI: SQL Injection vulnerability
    - ERROR: Execution or network error during testing
    """
    INFO = "info"
    PORT = "port"
    XSS = "xss"
    SQLI = "sqli"
    ERROR = "error"

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
    """
    type: FindingType
    detail: str
    url: Optional[str] = None
    payload: Optional[str] = None
    extra: Optional[Dict] = None