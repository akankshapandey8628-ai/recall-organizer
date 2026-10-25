import os
import re
import json
import mimetypes
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Load .env if present (local dev)
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv()

_client = None

def get_client():
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("[AI-Tagger] Warning: GEMINI_API_KEY is not set. AI tagging disabled.")
        return None
    try:
        from google import genai
        _client = genai.Client(api_key=api_key)
        return _client
    except Exception as e:
        print(f"[AI-Tagger] Failed to initialize Google GenAI client: {e}")
        return None

CANDIDATE_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
]

PROMPT = """Analyze this image for a digital personal organizer app.
Return a JSON object with EXACTLY these keys:
- "tags": list of 8 to 12 lowercase hashtags for organizing and searching (e.g. ["#swot", "#analysis", "#notes", "#planner"]). Include subject, brand/app, color, type of document/image.
- "summary": a clear 1-2 sentence description of what the image shows.
- "extracted_text": all text visible in the image so it can be searched (act as OCR). If no text, return empty string.
- "category": best single category among [College, Finance, Shopping, Food, Travel, Personal, General].

Reply ONLY with valid JSON. Nothing else."""

def analyze_image(image_path):
    """
    Analyzes an image using Gemini AI with model fallback.
    Returns dict:
      {
        "tags": list of tag strings (without #),
        "summary": str,
        "extracted_text": str,
        "category": str
      }
    """
    empty_result = {
        "tags": [],
        "summary": "",
        "extracted_text": "",
        "category": "General"
    }

    if not os.path.exists(image_path):
        print(f"[AI-Tagger] File not found: {image_path}")
        return empty_result

    client = get_client()
    if not client:
        return empty_result

    try:
        with open(image_path, "rb") as f:
            data = f.read()
    except Exception as e:
        print(f"[AI-Tagger] Failed to read {image_path}: {e}")
        return empty_result

    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    from google.genai import types

    for model_name in CANDIDATE_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[types.Part.from_bytes(data=data, mime_type=mime), PROMPT],
            )
            raw = (response.text or "").strip()
            # Clean markdown codeblocks
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE).strip()

            parsed = json.loads(raw)

            # Normalize tags
            raw_tags = parsed.get("tags") or []
            clean_tags = []
            _seen = set()
            for t in raw_tags:
                n = re.sub(r"[^a-zA-Z0-9_-]", "", str(t)).strip().lower()
                if n and n not in _seen:
                    _seen.add(n)
                    clean_tags.append(n)

            # If tags is empty, fallback to regex
            if not clean_tags:
                found_tags = re.findall(r"#(\w+)", raw.lower())
                clean_tags = list(dict.fromkeys(found_tags))[:10]

            return {
                "tags": clean_tags[:12],
                "summary": str(parsed.get("summary") or "").strip(),
                "extracted_text": str(parsed.get("extracted_text") or "").strip(),
                "category": str(parsed.get("category") or "General").strip()
            }
        except Exception as err:
            print(f"[AI-Tagger] Model {model_name} failed: {err}")
            continue

    print(f"[AI-Tagger] All candidate models failed for {image_path}")
    return empty_result


def generate_tags(image_path):
    """
    Backwards-compatible function for app.py.
    Returns list of tags (without #).
    """
    result = analyze_image(image_path)
    return result.get("tags", [])


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        res = analyze_image(sys.argv[1])
        print("Analysis:", json.dumps(res, indent=2))
