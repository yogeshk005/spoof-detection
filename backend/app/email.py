import boto3
from botocore.exceptions import BotoCoreError, ClientError
from .config import settings


class EmailDeliveryError(RuntimeError):
    pass


def send_otp_email(recipient: str, otp: str) -> None:
    if not recipient:
        raise EmailDeliveryError("No email address is enrolled for this identity.")
    if not settings.ses_from_email:
        raise EmailDeliveryError("SES_FROM_EMAIL is not configured.")

    client = boto3.client("ses", region_name=settings.aws_region)
    try:
        client.send_email(
            Source=settings.ses_from_email,
            Destination={"ToAddresses": [recipient]},
            Message={
                "Subject": {"Data": "BlinkCheck verification code", "Charset": "UTF-8"},
                "Body": {
                    "Text": {
                        "Data": (
                            f"Your BlinkCheck verification code is {otp}.\n\n"
                            "This code expires shortly. Do not share it with anyone."
                        ),
                        "Charset": "UTF-8",
                    }
                },
            },
        )
    except (BotoCoreError, ClientError) as exc:
        raise EmailDeliveryError("Amazon SES could not send the verification email.") from exc


def mask_email(address: str) -> str:
    local, domain = address.split("@", 1)
    visible = local[:1]
    return f"{visible}{'*' * max(1, len(local) - 1)}@{domain}"
