import os
import re
import hashlib
from datetime import datetime

ALLOWED_IMAGE_EXT = {'png', 'jpg', 'jpeg', 'jfif', 'gif', 'webp', 'bmp', 'heic', 'heif'}
ALLOWED_PDF_EXT   = {'pdf'}
ALLOWED_EXT       = ALLOWED_IMAGE_EXT | ALLOWED_PDF_EXT
MAX_CONTENT_MB    = 50

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

def is_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXT

def is_pdf(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_PDF_EXT

def now_iso():
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

def clean_text(text):
    if not text:
        return ''
    cleaned = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r'\n\s*\n+', '\n\n', cleaned)
    return cleaned.strip()

def compute_content_hash(text_or_bytes):
    if isinstance(text_or_bytes, str):
        data = text_or_bytes.encode('utf-8')
    elif isinstance(text_or_bytes, (bytes, bytearray)):
        data = text_or_bytes
    else:
        data = str(text_or_bytes).encode('utf-8')
    return hashlib.sha256(data).hexdigest()[:16]
