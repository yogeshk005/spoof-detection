from app.decision import decide

def test_strong_scores_allow():
    assert decide(99, 98).outcome == "ALLOW"

def test_low_liveness_denies():
    result = decide(70, 99)
    assert result.outcome == "DENY"
    assert result.reason_code == "SPOOF_DETECTED"

def test_uncertainty_band_requests_otp():
    result = decide(88, 97)
    assert result.outcome == "REQUEST VERIFICATION"
    assert result.action == "OTP_ONLY"

def test_low_match_denies():
    assert decide(99, 80).reason_code == "IDENTITY_MISMATCH"

def test_integrity_failure_denies():
    assert decide(99, 99, integrity_ok=False).reason_code == "INJECTION_SUSPECTED"
