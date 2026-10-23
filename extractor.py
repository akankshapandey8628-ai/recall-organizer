import re
from datetime import datetime
import dateparser

DATE_PATTERNS = [
    r'\b(?:due\s*(?:date|on|by)?[:\s]+)?((?:0?[1-9]|[12][0-9]|3[01])[-/.](?:0?[1-9]|1[012])[-/.](?:20\d\d|\d\d))\b',
    r'\b((?:20\d\d)[-/.](?:0?[1-9]|1[012])[-/.](?:0?[1-9]|[12][0-9]|3[01]))\b',
    r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(?:0?[1-9]|[12][0-9]|3[01])(?:st|nd|rd|th)?(?:,?\s+(?:20)?\d\d)?)\b',
    r'\b((?:0?[1-9]|[12][0-9]|3[01])(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?:,?\s+(?:20)?\d\d)?)\b'
]

AMOUNT_PATTERN = r'(?:₹|Rs\.?|INR|\$|USD|EUR|€)\s*([0-9,]+(?:\.[0-9]{1,2})?)'

LOCATION_KEYWORDS = [
    'Delhi', 'New Delhi', 'Mumbai', 'Bangalore', 'Bengaluru', 'Goa', 'Pune', 'Hyderabad',
    'Kolkata', 'Chennai', 'Jaipur', 'Ahmedabad', 'Noida', 'Gurugram', 'Chandigarh',
    'Airport', 'Terminal', 'Railway Station', 'Hotel', 'Resort', 'Campus', 'Hospital'
]

ID_PATTERNS = [
    ('PNR', r'\b([0-9]{10})\b'),
    ('Order ID', r'\b(?:Order\s*(?:ID|#)?[:\s]*)([A-Z0-9-]{6,25})\b'),
    ('Invoice #', r'\b(?:Invoice\s*(?:No|Number|#)?[:\s]*)([A-Z0-9/-]{4,20})\b'),
    ('Roll No', r'\b(?:Roll\s*(?:No|Num|Number)?[:\s]*)([A-Z0-9-]{4,15})\b'),
    ('Tracking #', r'\b(?:AWB|Tracking\s*(?:ID|#)?[:\s]*)([0-9]{8,18})\b')
]

def extract_entities(text):
    if not text:
        return {'dates': [], 'amounts': [], 'locations': [], 'ids': []}

    entities = {'dates': [], 'amounts': [], 'locations': [], 'ids': []}
    now = datetime.now()

    # 1. Dates
    found_dates = set()
    for pat in DATE_PATTERNS:
        for match in re.finditer(pat, text, re.IGNORECASE):
            raw = match.group(1).strip()
            if raw and raw not in found_dates:
                found_dates.add(raw)
                dt = dateparser.parse(raw, settings={'PREFER_DATES_FROM': 'future'})
                if dt:
                    is_future = dt.date() >= now.date()
                    entities['dates'].append({
                        'raw': raw,
                        'formatted': dt.strftime('%d %b %Y'),
                        'iso': dt.strftime('%Y-%m-%d'),
                        'is_future': is_future
                    })
            if len(entities['dates']) >= 4:
                break
        if len(entities['dates']) >= 4:
            break

    # 2. Amounts
    found_amounts = set()
    for match in re.finditer(AMOUNT_PATTERN, text, re.IGNORECASE):
        prefix = text[max(0, match.start()-1):match.start()+1].strip()
        val = match.group(1).strip()
        amt_str = f"₹{val}" if ('₹' in prefix or 'rs' in prefix.lower() or 'inr' in prefix.lower()) else f"${val}"
        if amt_str not in found_amounts:
            found_amounts.add(amt_str)
            entities['amounts'].append(amt_str)
        if len(entities['amounts']) >= 4:
            break

    # 3. Locations
    found_locs = set()
    for loc in LOCATION_KEYWORDS:
        if re.search(r'\b' + re.escape(loc) + r'\b', text, re.IGNORECASE):
            found_locs.add(loc)
            entities['locations'].append(loc)
        if len(entities['locations']) >= 4:
            break

    # 4. IDs
    found_ids = set()
    for id_type, pat in ID_PATTERNS:
        matches = re.findall(pat, text, re.IGNORECASE)
        for m in matches:
            if m not in found_ids and len(m) >= 4:
                found_ids.add(m)
                entities['ids'].append({'type': id_type, 'value': m})
                break
        if len(entities['ids']) >= 4:
            break

    return entities
