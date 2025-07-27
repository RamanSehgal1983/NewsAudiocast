"""
Utility Functions (utils.py)

This module contains small, reusable helper functions that are used across
different parts of the application. Keeping them here helps to avoid code
duplication and maintain a clean project structure.

Includes:
- `build_full_url`: Constructs a Google News RSS URL with region/language parameters.
- `send_email`: Sends emails with optional attachments using SMTP.
"""
import smtplib
import os
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from config import SENDER_EMAIL, SENDER_PASSWORD

logger = logging.getLogger(__name__)

def build_full_url(base_url, region):
    """Appends region and language parameters to a base URL."""
    if region:
        separator = '&' if '?' in base_url else '?'
        return f"{base_url}{separator}gl={region}&hl=en"
    return base_url

def send_email(recipient_email, subject, body, attachment_path=None):
    """
    Sends an email using configured SMTP settings.

    Can send plain text emails or emails with a single attachment.

    Args:
        recipient_email (str): The email address of the recipient.
        subject (str): The subject of the email.
        body (str): The plain text body of the email.
        attachment_path (str, optional): The file path of the attachment. Defaults to None.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        logger.error("Email credentials (SENDER_EMAIL, SENDER_PASSWORD) are not configured.")
        return False

    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = recipient_email
    msg['Subject'] = subject

    # Attach the body as plain text
    msg.attach(MIMEText(body, 'plain'))

    # Handle attachment if provided
    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, 'rb') as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(attachment_path)}"')
            msg.attach(part)
        except Exception as e:
            logger.error(f"Failed to read or attach file {attachment_path}: {e}")
            return False

    # Send the email
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        logger.info(f"Email sent successfully to {recipient_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {recipient_email}: {e}")
        return False