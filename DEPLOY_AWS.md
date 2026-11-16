# BlinkCheck — AWS deployment guide

This is a practical demo deployment. Validate service availability, quotas, pricing and regional support in your account before creating resources. Choose a region where **Rekognition Face Liveness is enabled**; do not assume `ap-south-1`.

## 1. Choose the region and create an S3 bucket

**Goal:** store enrolled reference images privately.

1. In AWS Console, choose a supported region.
2. Open S3 → Create bucket.
3. Name it globally uniquely, e.g. `blinkcheck-enrollment-<account-id>-<region>`.
4. Keep Block Public Access enabled, enable default encryption (SSE-S3 or SSE-KMS), and enable versioning if audit policy requires it.
5. Do not enable static website hosting on this bucket.

Set backend environment:
- `AWS_REGION=<supported-region>`
- `S3_BUCKET=<bucket-name>`
- `MOCK_MODE=false`

**Verify:** upload a test object through an authorized role and confirm it is private.

## 2. Create least-privilege IAM roles

**Goal:** grant only the API and browser the permissions they need.

Create an ECS task role `BlinkCheckApiTaskRole`. Attach a policy scoped to the chosen region and bucket:
- `rekognition:CreateFaceLivenessSession`
- `rekognition:GetFaceLivenessSessionResults`
- `rekognition:CompareFaces`
- `rekognition:DetectFaces`
- `s3:PutObject`, `s3:GetObject` on `arn:aws:s3:::<bucket-name>/enrollments/*`

Add CloudWatch Logs permissions through the standard ECS task execution role, not broad administrator access. The API role should not have `s3:*` or `rekognition:*`.

Create a Cognito Identity Pool for unauthenticated browser liveness streaming only if using the browser SDK. Its unauthenticated role must have only the permissions required by the currently documented Face Liveness streaming SDK flow, scoped to the selected region. Do not give the browser S3 access, `CompareFaces`, or enrollment-object permissions. Review the current AWS Amplify/Rekognition documentation before attaching this policy; SDK requirements can change.

**Verify:** inspect the IAM policy simulator and confirm unrelated S3 buckets and Rekognition actions are denied.

## 3. Create the database

**Goal:** persist credentials, enrollments, attempts and audit events across deployments.

1. Open RDS → Create database → PostgreSQL.
2. Select a small burstable instance for a demo, private access, storage encryption and automated backups.
3. Place it in private subnets.
4. Create a security group `blinkcheck-rds-sg` allowing TCP 5432 only from the API task security group.
5. Store the database username/password in AWS Secrets Manager.

Set:
- `DATABASE_URL=postgresql+psycopg://<user>:<password>@<rds-endpoint>:5432/blinkcheck`

**Verify:** from the API task network, connect with `psql` and run `SELECT 1;`. Do not expose RDS publicly.

## 4. Build and publish the API container

**Goal:** package the FastAPI service.

From the project root:

```bash
aws ecr create-repository --repository-name blinkcheck-api
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <account-id>.dkr.ecr.<region>.amazonaws.com
docker build -t blinkcheck-api ./backend
docker tag blinkcheck-api:latest <account-id>.dkr.ecr.<region>.amazonaws.com/blinkcheck-api:latest
docker push <account-id>.dkr.ecr.<region>.amazonaws.com/blinkcheck-api:latest
```

**Verify:** ECR → Repositories → `blinkcheck-api` shows the pushed image.

## 5. Deploy API on ECS Fargate

**Goal:** run the backend without managing servers.

1. Open ECS → Create cluster.
2. Create a Fargate task definition using the ECR image. Container port: `8000`.
3. Set task role to `BlinkCheckApiTaskRole`; execution role to the ECS task execution role.
4. Configure environment variables:
   - `MOCK_MODE=false`
   - `AWS_REGION=<supported-region>`
   - `S3_BUCKET=<bucket-name>`
   - `DATABASE_URL` from Secrets Manager
   - `CORS_ORIGINS=https://<frontend-domain>`
   - `OTP_SECRET` from Secrets Manager (generate a long random value)
   - `SESSION_TTL_SECONDS=180`
5. Create an ECS service in private subnets with a load balancer.
6. Create an ALB security group allowing inbound HTTPS 443 from the internet; API task security group allows inbound 8000 only from ALB security group.
7. Configure ALB target group health check path `/api/health`.

**Verify:** target group reports healthy and `https://<api-domain>/api/health` returns `{"status":"ok"}`.

## 6. Configure Cognito for the liveness browser SDK

**Goal:** let the browser SDK obtain temporary credentials for the liveness stream without exposing long-term AWS keys.

1. Create a Cognito Identity Pool in the same supported region.
2. Enable guest access only if the demo requires it.
3. Review the current AWS Amplify Face Liveness setup instructions and attach the minimal documented streaming permissions to the unauthenticated role.
4. Set frontend variables:
   - `VITE_AWS_REGION=<supported-region>`
   - `VITE_COGNITO_IDENTITY_POOL_ID=<identity-pool-id>`
   - `VITE_API_BASE_URL=https://<api-domain>`

Never put IAM access keys, secret keys, database passwords, or the OTP secret in frontend variables.

**Verify:** browser obtains temporary Cognito credentials and the liveness component can connect to a test session. If the SDK permission model has changed, follow the current AWS SDK documentation rather than broadening permissions.

## 7. Configure the frontend

**Goal:** host the static web app over HTTPS.

```bash
cd frontend
npm ci
npm run build
aws s3 sync dist/ s3://<frontend-bucket> --delete
```

Use CloudFront with the S3 bucket as a private origin (Origin Access Control). Request an ACM certificate in `us-east-1` for a CloudFront custom domain, validate DNS, and attach it to the distribution. Configure SPA fallback to `/index.html`.

Set `VITE_API_BASE_URL`, `VITE_AWS_REGION`, and `VITE_COGNITO_IDENTITY_POOL_ID` at build time before `npm run build`.

**Verify:** open the HTTPS frontend domain, confirm the camera-first verification screen loads, allow camera access, and confirm API calls succeed without CORS errors.

## 8. Configure secrets, privacy and retention

**Goal:** protect biometric data and minimize retention.

- Keep `OTP_SECRET` and DB credentials in Secrets Manager.
- Use task IAM roles instead of static AWS credentials.
- Keep S3 private and encrypted; restrict object access to the API task role.
- Define explicit consent, purpose limitation, retention and deletion procedures.
- Review India's Digital Personal Data Protection Act and applicable rules with qualified counsel before processing real biometric data.
- Set a short retention period for audit images; store reason codes and metadata where possible instead of images.
- Never log raw face images, OTP values, access tokens or secrets.

**Verify:** inspect CloudTrail and S3 access logs; confirm public access is blocked and secrets are not present in task definitions as plaintext.

## 9. Logging and monitoring

**Goal:** detect failures and suspicious activity.

- Send ECS container logs to CloudWatch Logs.
- Create alarms for API 5xx errors, task restarts, high latency, RDS CPU/storage, and repeated verification denials.
- Alert on `INJECTION_SUSPECTED`, lockouts and hill-climbing signals.
- Record per-stage latency: capture complete → decision shown, not the time from opening the camera.
- Run at least 100 timed trials and report mean, P95 and P99 latency.
- Test print, screen replay, video replay and (where safely available) mask attempts. Report measured APCER/BPCER with confidence intervals; do not claim FAR below 0.01% from a small sample.

**Verify:** trigger a test application error and confirm it appears in CloudWatch; trigger a test alarm and confirm notification delivery.

## 10. End-to-end verification

1. Enroll a test badge holder using a live enrollment session.
2. Tap/enter the same badge and complete a fresh liveness session.
3. Confirm matching uses the session `ReferenceImage`, not a browser upload.
4. Confirm a strong result returns `ALLOW`.
5. Force an uncertainty-band score in a test environment and verify `REQUEST VERIFICATION` plus OTP only.
6. Verify wrong OTP, expired OTP and reused OTP are rejected.
7. Make three scored attempts inside 15 minutes and confirm lockout.
8. Simulate service unavailability and confirm fail-closed behavior.
9. Confirm audit events, reason codes and latency are visible.
10. Confirm the live site uses HTTPS and RDS/S3 are not public.

## Troubleshooting — five likely failures

| Symptom | Likely cause | Fix |
|---|---|---|
| Face Liveness session creation fails | Unsupported region, feature not enabled, quota or IAM issue | Check regional availability, account access, quotas and task-role permissions |
| Liveness detector cannot stream | Cognito identity pool or browser SDK credentials/policy misconfigured | Check region, identity pool ID, guest role and current SDK permission requirements |
| API returns 403/AccessDenied for image operations | Task role missing scoped S3 or Rekognition permission | Add only the required action and resource to the ECS task role |
| Frontend reports CORS/network errors | Wrong API URL, ALB health check or CORS origin | Check `VITE_API_BASE_URL`, target health, HTTPS and exact `CORS_ORIGINS` |
| Database connection fails | Wrong secret/URL, subnet or security group | Check RDS endpoint, credentials, private routing and TCP 5432 ingress from API task SG |

## Cost-awareness

For a short demo, stop/delete ECS services, ALB, RDS and NAT gateways when not in use. NAT gateways and always-on RDS/ALB can cost more than expected. Rekognition Face Liveness is usage-priced; check current regional pricing and set a budget alarm. Prefer private subnets with carefully planned egress; do not leave resources running indefinitely.
