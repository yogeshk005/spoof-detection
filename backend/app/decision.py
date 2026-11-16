from dataclasses import dataclass

@dataclass
class Decision:
    outcome: str
    reason_code: str
    action: str

def decide(liveness: float, match: float, integrity_ok: bool = True,
           quality_ok: bool = True) -> Decision:
    if not quality_ok:
        return Decision("REQUEST VERIFICATION", "QUALITY_GATE_FAILED", "RESCAN_MAX_3")
    if not integrity_ok:
        return Decision("DENY", "INJECTION_SUSPECTED", "LOCK_AND_ALERT")
    if liveness < 85:
        return Decision("DENY", "SPOOF_DETECTED", "STOP")
    if match < 85:
        return Decision("DENY", "IDENTITY_MISMATCH", "STOP")
    if liveness < 90 or match <= 95:
        return Decision("REQUEST VERIFICATION", "UNCERTAINTY_BAND", "OTP_ONLY")
    return Decision("ALLOW", "VERIFIED", "ISSUE_SESSION_TOKEN")
