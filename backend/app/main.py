import json, time
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, inspect, text
from .config import settings
from .db import Base, engine, get_db
from .models import Person, Verification, AuditEvent
from .schemas import EnrollStart, VerifyStart, OtpVerify
from .decision import decide
from .pad import PassivePad
from .security import new_mock_session, make_otp, verify_otp
from .aws_adapter import get_aws_biometrics
from .email import EmailDeliveryError, mask_email, send_otp_email
from .embedding import EmbeddingUnavailable, get_face_embedding

Base.metadata.create_all(bind=engine)
if "email" not in {column["name"] for column in inspect(engine).get_columns("people")}:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE people ADD COLUMN email VARCHAR(320)"))
if "embedding_json" not in {column["name"] for column in inspect(engine).get_columns("people")}:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE people ADD COLUMN embedding_json TEXT"))
app = FastAPI(title=settings.app_name, version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",")],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
pad = PassivePad()

def utcnow():
    return datetime.now(timezone.utc)

def expired(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value < utcnow()

def audit(db, person_id, session_id, decision, reason, latency, details=None):
    db.add(AuditEvent(person_id=person_id, session_id=session_id, decision=decision,
                      reason_code=reason, latency_ms=latency,
                      details=json.dumps(details or {})))
    db.commit()

def check_lockout(db: Session, person_id: int):
    since = utcnow() - timedelta(seconds=settings.attempt_window_seconds)
    recent = db.scalars(select(Verification).where(
        Verification.person_id == person_id,
        Verification.created_at >= since,
        Verification.status.in_(["ALLOW", "DENY", "REQUEST VERIFICATION"])
    )).all()
    if len(recent) >= settings.max_scored_attempts:
        raise HTTPException(429, "Identity is temporarily locked. Try again after the lockout window.")

def supersede_open_sessions(db: Session, person_id: int):
    sessions = db.scalars(select(Verification).where(
        Verification.person_id == person_id,
        Verification.used.is_(False)
    )).all()
    for session in sessions:
        session.used = True
        session.status = "SUPERSEDED"

def aws_biometrics():
    return get_aws_biometrics()

def encode_enrollment(image_bytes: bytes) -> str:
    try:
        return json.dumps(get_face_embedding().encode(image_bytes))
    except EmbeddingUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "blinkcheck-api", "mode": "mock" if settings.mock_mode else "aws"}

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    people = db.scalars(select(Person).order_by(Person.created_at.desc())).all()
    events = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(12)).all()
    return {
        "people": [{"credential_id": p.credential_id, "display_name": p.display_name, "enrolled": p.enrolled} for p in people],
        "events": [{"id": e.id, "decision": e.decision, "reason_code": e.reason_code,
                    "latency_ms": e.latency_ms, "created_at": e.created_at.isoformat()} for e in events],
        "stats": {"enrolled": sum(p.enrolled for p in people), "total_events": db.query(AuditEvent).count(),
                  "denied": db.query(AuditEvent).filter(AuditEvent.decision == "DENY").count()}
    }

@app.post("/api/enrollment/start")
def enrollment_start(payload: EnrollStart, db: Session = Depends(get_db)):
    person = db.scalar(select(Person).where(Person.credential_id == payload.credential_id))
    if person is None:
        person = Person(credential_id=payload.credential_id, display_name=payload.display_name,
                        email=payload.email)
        db.add(person); db.commit(); db.refresh(person)
    else:
        supersede_open_sessions(db, person.id)
        person.display_name = payload.display_name
        person.email = payload.email
        person.enrolled = False
        person.reference_s3_key = None
        db.commit()
    if settings.mock_mode:
        session_id = new_mock_session()
    else:
        try:
            session_id = aws_biometrics().create_liveness_session()
        except Exception as exc:
            raise HTTPException(502, f"Could not create AWS liveness session: {type(exc).__name__}")
    v = Verification(session_id=session_id, person_id=person.id, purpose="enroll",
                     expires_at=utcnow()+timedelta(seconds=settings.session_ttl_seconds))
    db.add(v); db.commit()
    return {"session_id": session_id, "credential_id": person.credential_id,
            "mock_mode": settings.mock_mode, "expires_in": settings.session_ttl_seconds}

@app.post("/api/enrollment/{session_id}/complete")
def enrollment_complete(session_id: str, db: Session = Depends(get_db)):
    v = db.scalar(select(Verification).where(Verification.session_id == session_id))
    if not v or v.purpose != "enroll" or v.used:
        raise HTTPException(404, "Enrollment session not found or already used.")
    if expired(v.expires_at):
        raise HTTPException(410, "Enrollment session expired.")
    person = db.get(Person, v.person_id)
    if not person:
        raise HTTPException(409, "Identity was removed. Start enrollment again.")
    if settings.mock_mode:
        # Demo enrollment marker only; no face is captured or stored.
        reference_key = "mock-enrollment"
    else:
        try:
            result = aws_biometrics().get_liveness_result(session_id)
            if result["status"] != "SUCCEEDED" or not result["reference_image"]:
                raise HTTPException(422, "Liveness enrollment did not succeed.")
            reference_key = aws_biometrics().save_enrollment_reference(
                person.credential_id, result["reference_image"])
            embedding_json = encode_enrollment(result["reference_image"])
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, f"AWS enrollment failed: {type(exc).__name__}")
    person.enrolled = True
    person.reference_s3_key = reference_key
    if not settings.mock_mode:
        person.embedding_json = embedding_json
    v.used = True; v.status = "ENROLLED"
    db.commit()
    audit(db, person.id, session_id, "ENROLLED", "ENROLLMENT_LIVENESS_PASSED", 0)
    return {"status": "ENROLLED", "credential_id": person.credential_id}

@app.post("/api/verification/preview")
def verification_preview(session_id: str = Form(...), image: UploadFile = File(...),
                         db: Session = Depends(get_db)):
    verification = db.scalar(select(Verification).where(
        Verification.session_id == session_id,
        Verification.purpose == "verify"
    ))
    if not verification or verification.used or expired(verification.expires_at):
        raise HTTPException(404, "Verification preview session is unavailable.")
    person = db.get(Person, verification.person_id)
    if not person or not person.enrolled or not person.reference_s3_key:
        raise HTTPException(409, "Identity is not enrolled.")
    try:
        current = get_face_embedding().encode(image.file.read())
        if person.embedding_json:
            enrolled = json.loads(person.embedding_json)
        else:
            reference = aws_biometrics().get_enrollment_reference(person.reference_s3_key)
            enrolled = get_face_embedding().encode(reference)
            person.embedding_json = json.dumps(enrolled)
            db.commit()
        score = get_face_embedding().similarity(current, enrolled)
    except EmbeddingUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Embedding preview failed: {type(exc).__name__}") from exc
    return {
        "session_id": session_id,
        "status": "PRELIMINARY",
        "decision": "MATCH" if score >= 75 else "NO_MATCH",
        "score": round(score, 2),
        "final_authority": "AWS_FACE_LIVENESS_AND_FACE_MATCH"
    }

@app.post("/api/verification/start")
def verification_start(payload: VerifyStart, db: Session = Depends(get_db)):
    person = db.scalar(select(Person).where(Person.credential_id == payload.credential_id))
    if not person or not person.enrolled:
        raise HTTPException(404, "Credential is not enrolled.")
    check_lockout(db, person.id)
    if settings.mock_mode:
        session_id = new_mock_session()
    else:
        try:
            session_id = aws_biometrics().create_liveness_session()
        except Exception as exc:
            raise HTTPException(502, f"Could not create AWS liveness session: {type(exc).__name__}")
    ratchet_since = utcnow() - timedelta(seconds=settings.lockout_seconds)
    recent_risk = db.scalars(select(AuditEvent).where(
        AuditEvent.person_id == person.id,
        AuditEvent.created_at >= ratchet_since,
        AuditEvent.decision.in_(["DENY", "REQUEST VERIFICATION"])
    )).first()
    v = Verification(session_id=session_id, person_id=person.id, purpose="verify",
                     ratchet_required=bool(recent_risk),
                     expires_at=utcnow()+timedelta(seconds=settings.session_ttl_seconds))
    db.add(v); db.commit()
    return {"session_id": session_id, "mock_mode": settings.mock_mode,
            "expires_in": settings.session_ttl_seconds}

@app.post("/api/verification/{session_id}/complete")
def verification_complete(session_id: str, db: Session = Depends(get_db)):
    started = time.perf_counter()
    timings = {}
    v = db.scalar(select(Verification).where(Verification.session_id == session_id))
    if not v or v.purpose != "verify" or v.used:
        raise HTTPException(404, "Verification session not found or already used.")
    if expired(v.expires_at):
        raise HTTPException(410, "Verification session expired.")
    person = db.get(Person, v.person_id)
    if not person or not person.enrolled:
        raise HTTPException(409, "Identity is not enrolled.")
    try:
        if settings.mock_mode:
            live_score, match_score = 97.0, 97.0
        else:
            aws = aws_biometrics()
            stage_started = time.perf_counter()
            result = aws.get_liveness_result(session_id)
            timings["liveness_result_ms"] = int((time.perf_counter() - stage_started) * 1000)
            if result["status"] != "SUCCEEDED" or not result["reference_image"]:
                raise HTTPException(422, "Liveness session did not succeed.")
            live_score = result["confidence"]
            # Crucially, match only the AWS session ReferenceImage against enrolled S3 image.
            stage_started = time.perf_counter()
            match_score = aws.compare_reference_to_enrollment(result["reference_image"],
                                                               person.reference_s3_key)
            timings["face_match_ms"] = int((time.perf_counter() - stage_started) * 1000)
        pad_result = pad.evaluate()
        integrity_ok = True  # Trusted-kiosk attestation is not available in browser demo.
        outcome = decide(live_score, match_score, integrity_ok=integrity_ok)
        if v.ratchet_required and outcome.outcome == "ALLOW":
            from .decision import Decision
            outcome = Decision("REQUEST VERIFICATION", "RATCHET_STEP_UP", "OTP_ONLY")
        v.liveness_score, v.match_score, v.pad_score = live_score, match_score, pad_result.score
        v.used = True
        latency = int((time.perf_counter()-started)*1000)
        timings["total_ms"] = latency
        if outcome.outcome == "REQUEST VERIFICATION":
            v.status = "REQUEST VERIFICATION"
            db.commit()
            audit(db, person.id, session_id, outcome.outcome, outcome.reason_code, latency,
                  {"liveness": live_score, "match": match_score, "pad_signal": pad_result.signal,
                   "timings_ms": timings})
            otp = "123456" if settings.mock_mode else make_otp(session_id)
            if settings.mock_mode:
                delivery = {"channel": "demo", "recipient": None}
            else:
                try:
                    send_otp_email(person.email, otp)
                except EmailDeliveryError as exc:
                    raise HTTPException(502, str(exc)) from exc
                delivery = {"channel": "email", "recipient": mask_email(person.email)}
            return {"outcome": outcome.outcome, "reason_code": outcome.reason_code,
                    "action": "OTP_ONLY", "session_id": session_id, "demo_otp": otp,
                    "otp_delivery": delivery, "latency_ms": latency,
                    "timings_ms": timings,
                    "scores": {"liveness": live_score, "match": match_score}}
        v.status = outcome.outcome
        db.commit()
        audit(db, person.id, session_id, outcome.outcome, outcome.reason_code, latency,
              {"liveness": live_score, "match": match_score, "pad_signal": pad_result.signal,
               "timings_ms": timings})
        return {"outcome": outcome.outcome, "reason_code": outcome.reason_code,
                "action": outcome.action, "latency_ms": latency,
                "timings_ms": timings,
                "scores": {"liveness": live_score, "match": match_score}}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Verification service failed closed: {type(exc).__name__}")

@app.post("/api/verification/otp")
def otp_verify(payload: OtpVerify, db: Session = Depends(get_db)):
    v = db.scalar(select(Verification).where(Verification.session_id == payload.session_id))
    if not v or v.status != "REQUEST VERIFICATION":
        raise HTTPException(404, "OTP challenge not found.")
    if expired(v.expires_at):
        raise HTTPException(410, "OTP challenge expired.")
    if v.otp_attempts >= 3:
        raise HTTPException(429, "Maximum OTP attempts exceeded.")
    valid = payload.otp == "123456" if settings.mock_mode else verify_otp(v.session_id, payload.otp)
    if not valid:
        v.otp_attempts += 1
        db.commit()
        audit(db, v.person_id, v.session_id, "DENY", "OTP_INVALID", 0)
        raise HTTPException(401, "OTP is invalid.")
    v.status = "ALLOWED_WITH_OTP"
    db.commit()
    audit(db, v.person_id, v.session_id, "ALLOWED_WITH_OTP", "OTP_VERIFIED", 0)
    return {"outcome": "ALLOWED_WITH_OTP", "reason_code": "OTP_VERIFIED",
            "note": "OTP confirms possession of the registered factor; it does not prove liveness."}

@app.get("/api/events")
def events(db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100)).all()
    return [{"id": r.id, "decision": r.decision, "reason_code": r.reason_code,
             "latency_ms": r.latency_ms, "details": json.loads(r.details),
             "created_at": r.created_at.isoformat()} for r in rows]
