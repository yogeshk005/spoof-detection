from dataclasses import dataclass

@dataclass
class PadResult:
    score: float
    signal: str

class PassivePad:
    """Adapter seam. Replace this demo signal with a validated passive PAD model."""
    def evaluate(self, frames_metadata: dict | None = None) -> PadResult:
        # The mock does not inspect pixels and is not a security control.
        return PadResult(score=96.0, signal="DEMO_PAD_NOT_A_REAL_MODEL")
