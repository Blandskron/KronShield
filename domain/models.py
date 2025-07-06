from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict

class FindingType(str, Enum):
    INFO = "info"
    PORT = "port"
    XSS = "xss"
    SQLI = "sqli"
    ERROR = "error"

@dataclass
class Finding:
    type: FindingType
    detail: str
    url: Optional[str] = None
    payload: Optional[str] = None
    extra: Optional[Dict] = None