import os
import re
import mimetypes
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

PROMPT = """Look at this image and give 8 to 10 hashtags for organizing and searching it later.
Include, when visible: the brand/app/website name (e.g. flipkart, zomato, irctc),
what the item is (e.g. top, dress, shoes, pizza, ticket, bill),
its main color name (e.g. maroon, navy, pink),
the word 'screenshot' if it is a phone screenshot,
and one category (shopping, food, travel, finance, college, personal).
Reply ONLY with lowercase hashtags separated by spaces. Nothing else."""

def generate_tags(image_path):
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=[types.Part.from_bytes(data=data, mime_type=mime), PROMPT],
        )
        tags = re.findall(r"#\w+", response.text.lower())
        return list(dict.fromkeys(tags))[:10]
    except Exception as e:
        print("AI tagging failed:", e)
        return []

if __name__ == "__main__":
    import sys
    print(generate_tags(sys.argv[1]))