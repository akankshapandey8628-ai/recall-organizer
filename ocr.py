import os
import io
from utils import clean_text

OCR_AVAILABLE = False
try:
    from PIL import Image, ImageEnhance
    import pytesseract

    TESSERACT_CANDIDATES = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        os.path.expanduser(r'~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe')
    ]
    for candidate in TESSERACT_CANDIDATES:
        if os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            OCR_AVAILABLE = True
            break
    if not OCR_AVAILABLE:
        try:
            pytesseract.get_tesseract_version()
            OCR_AVAILABLE = True
        except Exception:
            OCR_AVAILABLE = False
except ImportError:
    OCR_AVAILABLE = False

PDF_AVAILABLE = False
try:
    import pypdf
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

def preprocess_image(img):
    try:
        if img.mode != 'L':
            img = img.convert('L')
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.8)
        w, h = img.size
        if w < 1000 and h < 1000:
            img = img.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
        return img
    except Exception:
        return img

def extract_text_from_image(filepath):
    if not OCR_AVAILABLE or not os.path.exists(filepath):
        return ''
    try:
        with Image.open(filepath) as img:
            proc = preprocess_image(img)
            text = pytesseract.image_to_string(proc, config='--oem 3 --psm 3')
            if not text.strip():
                text = pytesseract.image_to_string(proc, config='--oem 3 --psm 6')
            return clean_text(text)
    except Exception as e:
        print(f"OCR failed for {filepath}: {e}")
        return ''

def extract_text_from_pdf(filepath):
    if not PDF_AVAILABLE or not os.path.exists(filepath):
        return ''
    try:
        reader = pypdf.PdfReader(filepath)
        extracted = []
        for page in reader.pages:
            pt = page.extract_text() or ''
            if pt.strip():
                extracted.append(pt.strip())
            elif OCR_AVAILABLE:
                page_ocr = []
                for img_obj in page.images:
                    try:
                        im = Image.open(io.BytesIO(img_obj.data))
                        proc = preprocess_image(im)
                        t = pytesseract.image_to_string(proc, config='--oem 3 --psm 6')
                        if t.strip():
                            page_ocr.append(t.strip())
                    except Exception:
                        continue
                if page_ocr:
                    extracted.append('\n'.join(page_ocr))
        return clean_text('\n\n'.join(extracted))
    except Exception as e:
        print(f"PDF extract error for {filepath}: {e}")
        return ''
