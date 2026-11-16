import uuid
import boto3
from functools import lru_cache
from botocore.exceptions import BotoCoreError, ClientError
from .config import settings

class AwsBiometrics:
    def __init__(self):
        self.client = boto3.client("rekognition", region_name=settings.aws_region)
        self.s3 = boto3.client("s3", region_name=settings.aws_region)

    def create_liveness_session(self) -> str:
        result = self.client.create_face_liveness_session()
        return result["SessionId"]

    def get_liveness_result(self, session_id: str) -> dict:
        result = self.client.get_face_liveness_session_results(SessionId=session_id)
        reference = result.get("ReferenceImage", {}).get("Bytes")
        return {
            "status": result.get("Status"),
            "confidence": float(result.get("Confidence", 0)),
            "reference_image": reference,
        }

    def save_enrollment_reference(self, credential_id: str, image_bytes: bytes) -> str:
        key = f"enrollments/{credential_id}/{uuid.uuid4().hex}.jpg"
        self.s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=image_bytes,
                           ContentType="image/jpeg", ServerSideEncryption="AES256")
        return key

    def get_enrollment_reference(self, s3_key: str) -> bytes:
        result = self.s3.get_object(Bucket=settings.s3_bucket, Key=s3_key)
        return result["Body"].read()

    def compare_reference_to_enrollment(self, reference_bytes: bytes, s3_key: str) -> float:
        result = self.client.compare_faces(
            SourceImage={"Bytes": reference_bytes},
            TargetImage={"S3Object": {"Bucket": settings.s3_bucket, "Name": s3_key}},
            SimilarityThreshold=0,
        )
        matches = result.get("FaceMatches", [])
        return max((float(item["Similarity"]) for item in matches), default=0.0)


@lru_cache(maxsize=1)
def get_aws_biometrics() -> AwsBiometrics:
    return AwsBiometrics()
