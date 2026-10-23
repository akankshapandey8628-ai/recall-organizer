import re

YAKE_AVAILABLE = False
try:
    import yake
    YAKE_AVAILABLE = True
except ImportError:
    YAKE_AVAILABLE = False

COMMON_STOPWORDS = {
    'the', 'is', 'at', 'which', 'on', 'and', 'a', 'an', 'in', 'to', 'for', 'of',
    'or', 'by', 'with', 'from', 'as', 'that', 'this', 'it', 'are', 'was', 'were',
    'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'but', 'not', 'you',
    'we', 'they', 'he', 'she', 'i', 'my', 'your', 'our', 'their', 'his', 'her'
}

def generate_smart_tags(text, max_tags=6):
    if not text or len(text.strip()) < 10:
        return []

    tags = []
    if YAKE_AVAILABLE:
        try:
            kw_extractor = yake.KeywordExtractor(
                lan="en",
                n=2,
                dedupLim=0.7,
                dedupFunc='seqm',
                windowsSize=1,
                top=max_tags * 2
            )
            keywords = kw_extractor.extract_keywords(text)
            for kw, score in keywords:
                cleaned = kw.strip().lower()
                if len(cleaned) > 2 and not cleaned.isdigit() and cleaned not in COMMON_STOPWORDS:
                    if cleaned not in tags:
                        tags.append(cleaned)
                if len(tags) >= max_tags:
                    break
        except Exception as e:
            print(f"YAKE tagger error: {e}")

    if not tags:
        words = re.findall(r'\b[a-zA-Z]{4,15}\b', text.lower())
        freq = {}
        for w in words:
            if w not in COMMON_STOPWORDS:
                freq[w] = freq.get(w, 0) + 1
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        tags = [w for w, _ in sorted_words[:max_tags]]

    return tags
