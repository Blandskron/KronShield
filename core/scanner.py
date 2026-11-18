from application.transport import SafeTransport
from domain.authorization import ScopeTarget
from domain.models import Finding, FindingType


def scan_authorized_port(target: ScopeTarget, transport: SafeTransport) -> Finding:
    """Probe exactly the port subject to the transport's scope decision."""
    if target.port is None:
        raise ValueError("TCP probe requires an effective port")
    peer = transport.tcp(target)
    return Finding(
        type=FindingType.PORT,
        detail=f"Puerto {target.port} abierto",
        extra={"port": target.port, "status": "open", "peer": str(peer)},
    )
