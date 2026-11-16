import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Amplify } from 'aws-amplify'
import { FaceLivenessDetector } from '@aws-amplify/ui-react-liveness'
import { Camera, ShieldCheck, ScanFace, Fingerprint, UserRound, RefreshCw, X, CheckCircle2, AlertTriangle, LockKeyhole } from 'lucide-react'

const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const REGION = import.meta.env.VITE_AWS_REGION || 'us-east-1'
const IDENTITY_POOL = import.meta.env.VITE_COGNITO_IDENTITY_POOL_ID

if (IDENTITY_POOL) {
  Amplify.configure({ Auth: { Cognito: { identityPoolId: IDENTITY_POOL, allowGuestAccess: true } } })
}

async function request(path, options = {}) {
  const isForm = options.body instanceof FormData
  const response = await fetch(`${API}${path}`, {
    headers: isForm ? { ...(options.headers || {}) } : { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`)
  return data
}

export default function App() {
  const videoRef = useRef(null)
  const streamRef = useRef(null)
  const completingSessionRef = useRef(null)
  const preliminarySessionRef = useRef(null)
  const [cameraReady, setCameraReady] = useState(false)
  const [cameraDeviceId, setCameraDeviceId] = useState('')
  const [cameraError, setCameraError] = useState('')
  const [credential, setCredential] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [mode, setMode] = useState('verify')
  const [session, setSession] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [result, setResult] = useState(null)
  const [otp, setOtp] = useState('')
  const [challenge, setChallenge] = useState(null)
  const [preliminary, setPreliminary] = useState(null)
  const [apiStatus, setApiStatus] = useState('checking')

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach(track => track.stop())
    streamRef.current = null
    setCameraReady(false)
  }, [])

  const openCamera = useCallback(async () => {
    setCameraError('')
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError('Camera access requires HTTPS or localhost and a supported browser.')
      return
    }
    try {
      stopCamera()
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } }
      })
      streamRef.current = stream
      setCameraDeviceId(stream.getVideoTracks()[0]?.getSettings().deviceId || '')
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play().catch(() => {})
      }
      setCameraReady(true)
    } catch (error) {
      setCameraError(error.name === 'NotAllowedError'
        ? 'Camera permission was blocked. Allow camera access in your browser settings and try again.'
        : 'Unable to open the camera. Check that it is connected and not being used by another app.')
    }
  }, [stopCamera])

  useEffect(() => {
    openCamera()
    request('/api/health').then(() => setApiStatus('online')).catch(() => setApiStatus('offline'))
    return () => stopCamera()
  }, [openCamera, stopCamera])

  async function startVerify() {
    if (credential.trim().length < 3) {
      setMessage('Enter or tap your HID badge / credential ID first.')
      return
    }
    setBusy(true); setMessage(''); setResult(null); setChallenge(null); setPreliminary(null)
    try {
      const preview = mode === 'verify' ? await capturePreview() : null
      stopCamera()
      const data = await request(mode === 'enroll' ? '/api/enrollment/start' : '/api/verification/start', {
        method: 'POST',
        body: JSON.stringify({
          credential_id: credential.trim(),
          ...(mode === 'enroll' ? {
            display_name: displayName.trim() || 'Badge Holder',
            email: email.trim()
          } : {})
        })
      })
      const nextSession = { ...data, kind: mode }
      setSession(nextSession)
      if (preview && !data.mock_mode) {
        const form = new FormData()
        form.append('session_id', data.session_id)
        form.append('image', preview, 'verification-preview.jpg')
        preliminarySessionRef.current = data.session_id
        request('/api/verification/preview', { method: 'POST', body: form })
          .then(previewResult => {
            if (preliminarySessionRef.current === previewResult.session_id) {
              setPreliminary(previewResult)
            }
          })
          .catch(() => {})
      }
      if (data.mock_mode) {
        setMessage('Demo mode is enabled. Completing the simulated result…')
        await completeSession(nextSession)
      } else if (!IDENTITY_POOL) {
        setMessage('Missing Cognito Identity Pool configuration. Add it to frontend/.env before live liveness verification.')
      }

      async function capturePreview() {
        if (!videoRef.current || videoRef.current.readyState < 2) return null
        const canvas = document.createElement('canvas')
        canvas.width = videoRef.current.videoWidth
        canvas.height = videoRef.current.videoHeight
        canvas.getContext('2d').drawImage(videoRef.current, 0, 0)
        return new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.82))
      }
    } catch (error) {
      setMessage(error.message)
      openCamera()
    } finally { setBusy(false) }
  }

  async function completeSession(activeSession = session) {
    if (!activeSession?.session_id || !['enroll', 'verify'].includes(activeSession.kind)) {
      setMessage('The verification session is missing. Start verification again.')
      return
    }
    if (completingSessionRef.current === activeSession.session_id) return
    completingSessionRef.current = activeSession.session_id
    setBusy(true); setMessage('Analysing liveness and matching the enrolled reference…')
    try {
      const path = activeSession.kind === 'enroll'
        ? `/api/enrollment/${activeSession.session_id}/complete`
        : `/api/verification/${activeSession.session_id}/complete`
      const data = await request(path, { method: 'POST' })
      setSession(null)
      preliminarySessionRef.current = null
      setPreliminary(null)
      if (activeSession.kind === 'enroll') {
        setResult({ outcome: 'ENROLLED', reason_code: 'ENROLLMENT_LIVENESS_PASSED' })
        setMessage('Face enrolled successfully. The liveness reference image was saved to your S3 bucket.')
      } else if (data.outcome === 'REQUEST VERIFICATION') {
        setChallenge(data)
        const recipient = data.otp_delivery?.recipient
        setMessage(recipient
          ? `An additional check is required. A code was sent to ${recipient}.`
          : 'An additional check is required. Enter the one-time code; rescanning is disabled for this attempt.')
      } else {
        setResult(data)
        setMessage('Verification process completed.')
      }
    } catch (error) {
      setMessage(error.message)
      setSession(null)
      completingSessionRef.current = null
      openCamera()
    } finally {
      setBusy(false)
    }
  }

  async function submitOtp(event) {
    event.preventDefault()
    if (!challenge) return
    setBusy(true)
    try {
      const data = await request('/api/verification/otp', {
        method: 'POST', body: JSON.stringify({ session_id: challenge.session_id, otp })
      })
      setResult(data); setChallenge(null); setOtp('')
      setMessage('Step-up verification completed.')
    } catch (error) { setMessage(error.message) }
    finally { setBusy(false) }
  }

  function resetFlow() {
    completingSessionRef.current = null
    preliminarySessionRef.current = null
    setSession(null); setResult(null); setChallenge(null); setOtp(''); setMessage('')
    setPreliminary(null)
    openCamera()
  }

  const liveMode = session && !session.mock_mode && IDENTITY_POOL
  const isSuccess = result?.outcome === 'ALLOW' || result?.outcome === 'ALLOWED_WITH_OTP' || result?.outcome === 'ENROLLED'
  const isDenied = result?.outcome === 'DENY'
  const currentTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const displayOutcome = result?.outcome || (session ? 'SCANNING' : 'READY')

  return <div className="page-shell">
    <header className="topbar">
      <a className="brand" href="#home"><span className="brand-mark"><ScanFace size={22}/></span><span>BlinkCheck<small>FACE IDENTITY ASSURANCE</small></span></a>
      <div className="topbar-right"><span className={`service-status ${apiStatus}`}><i/>{apiStatus === 'online' ? 'API CONNECTED' : apiStatus === 'offline' ? 'API OFFLINE' : 'CONNECTING'}</span><span className="secure-label"><LockKeyhole size={14}/> SECURE SESSION</span></div>
    </header>

    <main className="verify-layout" id="home">
      <div className="dashboard-heading">
        <div className="eyebrow"><span/> SECURE BIOMETRIC ACCESS SYSTEM</div>
        <h1>IDENTITY VERIFICATION</h1>
      </div>
      <section className="intro-block">
        <div className="scan-visual">
          <div className="scan-network"><ScanFace size={164}/><span className="scan-node node-one"/><span className="scan-node node-two"/><span className="scan-node node-three"/><span className="scan-node node-four"/></div>
          <div className="scan-confidence"><span>MATCH CONFIDENCE</span><strong>{result?.scores ? `${Number(result.scores.match).toFixed(0)}%` : '--%'}</strong></div>
          <div className="scan-bars"><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/><i/></div>
        </div>
        <div className="eyebrow"><span/> BIOMETRIC ACCESS CONTROL</div>
        <h2>Identity, verified.<br/><em>Access, protected.</em></h2>
        <p>Position your face inside the frame. BlinkCheck checks liveness first, then matches your verified face with the enrolled identity.</p>
        <div className="trust-points"><span><ShieldCheck size={17}/> AWS Rekognition</span><span><Fingerprint size={17}/> 1:1 identity match</span><span><LockKeyhole size={17}/> Encrypted reference storage</span></div>
      </section>

      <section className="camera-card">
        <div className="camera-card-head">
          <div><span className="eyebrow">LIVE CAMERA</span><h2>{session ? (session.kind === 'enroll' ? 'Secure enrollment' : 'Face verification') : 'Align your face'}</h2></div>
          <span className={`camera-state ${cameraReady || liveMode ? 'ready' : ''}`}><i/>{liveMode ? 'LIVENESS ACTIVE' : cameraReady ? 'CAMERA READY' : 'CAMERA OFF'}</span>
        </div>

        <div className={`camera-stage ${liveMode ? 'sdk-stage' : ''}`}>
          {!session && <>
            <video ref={videoRef} className={`camera-video ${cameraReady ? 'visible' : ''}`} autoPlay muted playsInline/>
            <div className="camera-shade"/>
            <div className="oval-guide"><span className="corner top-left"/><span className="corner top-right"/><span className="corner bottom-left"/><span className="corner bottom-right"/></div>
            {!cameraReady && <div className="camera-placeholder"><Camera size={34}/><b>Camera preview</b><span>{cameraError || 'Starting your camera…'}</span>{cameraError && <button className="secondary-btn" onClick={openCamera}><RefreshCw size={15}/> Enable camera</button>}</div>}
            {cameraReady && <div className="camera-hint">Keep your face centred in the oval</div>}
          </>}

          {session && session.mock_mode && <div className="mock-stage"><div className="mock-oval"><ScanFace size={54}/></div><b>DEMO SESSION</b><span>No live face analysis is performed in mock mode.</span></div>}
          {liveMode && <div className="liveness-container"><FaceLivenessDetector sessionId={session.session_id} region={REGION} disableStartScreen config={cameraDeviceId ? { deviceId: cameraDeviceId } : undefined} onAnalysisComplete={() => completeSession()} onError={(error) => { setMessage(error?.message || 'Liveness stream failed. Please retry.'); setSession(null); openCamera() }}/></div>}
          {preliminary && <div className="message-line"><ShieldCheck size={15}/><span>Preliminary identity: {preliminary.decision} ({Number(preliminary.score).toFixed(1)}%). Final result is pending AWS liveness.</span></div>}
          {session && !session.mock_mode && !IDENTITY_POOL && <div className="camera-placeholder config-warning"><AlertTriangle size={30}/><b>Live liveness is not configured</b><span>Set VITE_COGNITO_IDENTITY_POOL_ID in frontend/.env, then restart the frontend.</span></div>}
          {session && session.mock_mode && <button className="primary-btn demo-complete" onClick={() => completeSession()} disabled={busy}>{busy ? 'Processing…' : 'Complete demo verification'}</button>}
        </div>

        {!session && !challenge && !result && <div className="controls">
          <div className="mode-switch"><button className={mode === 'verify' ? 'active' : ''} onClick={() => { setMode('verify'); setMessage('') }}>Verify face</button><button className={mode === 'enroll' ? 'active' : ''} onClick={() => { setMode('enroll'); setMessage('') }}>Enroll face</button></div>
          <label className="field-label" htmlFor="credential">HID BADGE / CREDENTIAL ID</label>
          <div className="credential-field"><Fingerprint size={18}/><input id="credential" value={credential} onChange={e => setCredential(e.target.value)} placeholder="Tap badge or enter credential ID" autoComplete="off"/></div>
          {mode === 'enroll' && <><label className="field-label" htmlFor="display-name">NAME</label><div className="credential-field"><UserRound size={18}/><input id="display-name" value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder="Badge holder name"/></div><label className="field-label" htmlFor="email">EMAIL FOR STEP-UP VERIFICATION</label><div className="credential-field"><input id="email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="name@example.com" autoComplete="email"/></div></>}
          <button className="primary-btn" onClick={startVerify} disabled={busy || !cameraReady || credential.trim().length < 3 || (mode === 'enroll' && (displayName.trim().length < 2 || !email.includes('@')))}>{busy ? 'Starting secure session…' : mode === 'enroll' ? 'Start secure enrollment' : 'Start Verify'} <span>→</span></button>
          <p className="control-note">{mode === 'verify' ? 'Your badge selects one enrolled identity. Your live face is never searched against everyone.' : 'Enrollment also requires a successful liveness check before the reference image is stored.'}</p>
        </div>}

        {challenge && <form className="otp-panel" onSubmit={submitOtp}><div className="otp-heading"><LockKeyhole/><div><b>Additional verification</b><span>OTP required · no face rescan</span></div></div>{challenge.demo_otp && <p className="demo-otp">Demo code: <b>{challenge.demo_otp}</b></p>}<input value={otp} onChange={e => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="6-digit code" inputMode="numeric"/><button className="primary-btn" disabled={busy || otp.length !== 6}>Verify code →</button></form>}

        {result && <div className={`result-panel ${isSuccess ? 'success' : isDenied ? 'denied' : 'review'}`}><div className="result-icon">{isSuccess ? <CheckCircle2 size={27}/> : isDenied ? <AlertTriangle size={27}/> : <ShieldCheck size={27}/>}</div><div className="result-copy"><span className="eyebrow">VERIFICATION RESULT</span><h3>{result.outcome}</h3><p>{result.reason_code || 'Decision recorded'}</p>{result.scores && <small>Liveness {Number(result.scores.liveness).toFixed(1)}% · Face match {Number(result.scores.match).toFixed(1)}%</small>}</div><button className="close-result" onClick={resetFlow} aria-label="Start again"><RefreshCw size={17}/></button></div>}

        {message && <div className="message-line"><AlertTriangle size={15}/><span>{message}</span></div>}
        {session && <button className="cancel-btn" onClick={resetFlow}><X size={15}/> Cancel session</button>}
      </section>

      {(result || challenge) && <div className="identity-summary">
        <div className="summary-card"><ScanFace size={34}/><span>USER ID<strong>{credential || 'AWAITING CREDENTIAL'}</strong></span></div>
        <div className="summary-card"><Fingerprint size={34}/><span>SCAN METHOD<strong>FACIAL RECOGNITION</strong></span></div>
        <div className="summary-card"><span className="summary-clock">{currentTime}</span><span>TIME<strong>{currentTime}</strong></span></div>
        <div className={`summary-card summary-result ${isSuccess ? 'authenticated' : isDenied ? 'rejected' : ''}`}><ShieldCheck size={38}/><span>RESULT<strong>{displayOutcome}</strong></span></div>
      </div>}

      <div className="below-note"><ShieldCheck size={16}/><span>Face liveness is checked before identity matching. Reference images are stored in your configured private S3 bucket.</span></div>
    </main>
    <footer className="footer"><span>BLINKCHECK © 2026</span><span>Biometric prototype · Use only with informed consent and an approved retention policy.</span></footer>
  </div>
}
