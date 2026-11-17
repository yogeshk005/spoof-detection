# BlinkCheck

-Developed a camera-based biometric access-control solution during 12 hour HID Hackathon, combining real-time face liveness detection with HID badge-based identity verification.

## Main user experience

- When the app opens, the browser requests camera permission and displays a live camera preview inside an oval face guide.
- The user taps or enters their HID badge / credential ID. The badge selects one enrolled identity; it does not search every person in the database.
- The user clicks **Start Verify**. The browser's AWS Amplify `FaceLivenessDetector` streams the liveness session to Amazon Rekognition.
- The backend retrieves the session result and compares only the `ReferenceImage` returned by that same successful liveness session against the enrolled reference image stored privately in S3.
- The UI displays `ALLOW`, `REQUEST VERIFICATION`, or `DENY`.
- **Enroll face** is available on the same screen. Enrollment also requires a successful liveness session before its reference image is stored in S3.

## Important prototype boundaries

The default `MOCK_MODE=true` makes the app runnable locally without AWS. The camera preview still opens, but verification is simulated; it is not biometric evidence and must never control a real door. Use `MOCK_MODE=false`, a supported Rekognition region, a private S3 bucket, backend IAM permissions, and a Cognito Identity Pool for real AWS liveness.

The backend must use the `ReferenceImage` returned by the successful liveness session for matching. The browser does not upload a separate face image for identity matching. Session IDs are short-lived and single-use.

A browser prototype cannot reliably attest a trusted camera or detect all virtual-camera / remote-control injection. Production deployments should use a locked-down HID kiosk agent, signed capture frames, device attestation, and a security review.

The passive PAD module is an explicit adapter seam with a demo-only placeholder signal. It is not a real model and is not fused into an access decision. Replace it with a validated, licensed model and calibrate the fused risk score before production. Production OTP delivery is an integration point: connect a registered second factor through an approved push/SNS provider before real access control. The decision thresholds are starting values only and require ROC/DET calibration. No FAR/APCER/BPCER claim is made by this project.

## Requirements

- Python 3.11+
- Node.js 20+
- AWS account only for real liveness mode

## Run locally on Windows CMD

### 1. Backend

```cmd
cd backend
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs` to check the API.

### 2. Frontend (open a second CMD window)

```cmd
cd frontend
copy .env.example .env
npm install
npm run dev
```

Open `http://localhost:5173`. Allow camera access. The live preview should appear inside the oval guide. Camera preview starts on page load; AWS liveness streaming starts only after the user clicks **Start Verify**.

### 3. Demo flow

1. Select **Enroll face**.
2. Enter a badge ID and display name, then click **Start secure enrollment**.
3. In mock mode, click **Complete demo verification**. This is only a simulated enrollment; it does not store a real face in S3.
4. Switch to **Verify face**, enter the same badge ID, and click **Start Verify**.
5. In mock mode, click **Complete demo verification**. Demo OTP is `123456` and is displayed only in mock mode.

### 4. Real AWS mode

For real verification, set `MOCK_MODE=false` in `backend/.env`, configure `AWS_REGION` and `S3_BUCKET`, and supply AWS credentials through an IAM role or the standard AWS credential chain. Configure the frontend `.env` with `VITE_AWS_REGION` and `VITE_COGNITO_IDENTITY_POOL_ID`. The Cognito identity pool is used by the browser liveness SDK for temporary credentials; do not put AWS access keys in frontend variables.

Enroll each person through a live liveness session first. The backend stores the successful session's `ReferenceImage` as a private S3 object. During verification, the badge ID selects that person's S3 reference and `CompareFaces` compares it with the `ReferenceImage` from the current liveness session.

Use a Rekognition Face Liveness-supported region. Do not assume `ap-south-1` supports the feature; confirm availability in your AWS account before deployment.

## Tests

```cmd
cd backend
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest -q
```

## Configuration

See `backend/.env.example` and `frontend/.env.example`.

- `MOCK_MODE=true`: local simulation, no AWS liveness or S3 storage.
- `MOCK_MODE=false`: real Rekognition Face Liveness and S3 reference storage.
- `DATABASE_URL`: SQLAlchemy URL. SQLite is the default; use PostgreSQL for a multi-instance deployment.
- Never commit `.env` or AWS credentials.

## AWS deployment

Follow [DEPLOY_AWS.md](DEPLOY_AWS.md). Recommended topology:

- React/Vite frontend on S3 + CloudFront (HTTPS)
- FastAPI container on ECS Fargate behind an Application Load Balancer
- RDS PostgreSQL
- Private S3 bucket for enrollment reference images
- Rekognition Face Liveness in a region where the feature is enabled
- Cognito Identity Pool for browser liveness streaming
- CloudWatch logs and alarms

Review India's Digital Personal Data Protection Act, consent, retention, and deletion obligations before processing real biometric data.
