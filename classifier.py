import re

CATEGORY_RULES = {
    'College': {
        'keywords': [
            'assignment', 'lecture', 'homework', 'syllabus', 'semester', 'exam', 'university',
            'course', 'grade', 'attendance', 'professor', 'prof', 'lab', 'project', 'roll no',
            'student', 'cgpa', 'btech', 'mtech', 'bca', 'mca', 'college', 'campus', 'submission',
            'department', 'faculty', 'viva', 'practicals', 'curriculum', 'quiz', 'midsem', 'endsem'
        ],
        'subcategories': {
            'Assignment': ['assignment', 'homework', 'submission', 'due date', 'problem set'],
            'Exam & Grades': ['exam', 'quiz', 'midsem', 'endsem', 'grade', 'result', 'cgpa', 'marks', 'viva'],
            'Syllabus': ['syllabus', 'curriculum', 'course outline'],
            'Lecture & Notes': ['lecture', 'notes', 'chapter', 'unit', 'slide', 'module', 'professor']
        }
    },
    'Finance': {
        'keywords': [
            'invoice', 'receipt', 'bill', 'tax', 'payment', 'gst', 'bank', 'account', 'salary',
            'credited', 'debited', 'transfer', 'upi', 'neft', 'statement', 'due date', 'paid',
            'rupees', 'inr', 'rs', 'loan', 'emi', 'credit card', 'debit card', 'transaction',
            'balance', 'subtotal', 'total amount', 'net payable', 'premium', 'policy'
        ],
        'subcategories': {
            'Bill & Invoice': ['invoice', 'bill', 'tax invoice', 'gstin', 'net payable', 'due date'],
            'Receipt': ['receipt', 'paid', 'payment receipt', 'acknowledgement'],
            'Bank & Statement': ['bank', 'account', 'statement', 'transaction', 'credited', 'debited', 'upi'],
            'Salary & Tax': ['salary', 'payslip', 'tds', 'form 16', 'income tax', 'allowance']
        }
    },
    'Travel': {
        'keywords': [
            'ticket', 'boarding pass', 'flight', 'train', 'irctc', 'pnr', 'seat', 'berth',
            'hotel', 'booking', 'reservation', 'itinerary', 'passport', 'visa', 'departure',
            'arrival', 'bus', 'indigo', 'air india', 'stay', 'check-in', 'check-out',
            'passengers', 'terminal', 'gate', 'coach', 'station', 'airport', 'makemytrip'
        ],
        'subcategories': {
            'Flight & Train Ticket': ['flight', 'train', 'irctc', 'pnr', 'ticket', 'indigo', 'boarding pass', 'seat'],
            'Hotel Booking': ['hotel', 'stay', 'check-in', 'check-out', 'room', 'resort', 'reservation'],
            'Itinerary & Visa': ['itinerary', 'passport', 'visa', 'trip', 'travel plan', 'tour']
        }
    },
    'Food': {
        'keywords': [
            'recipe', 'restaurant', 'swiggy', 'zomato', 'menu', 'dinner', 'lunch', 'breakfast',
            'cooking', 'ingredients', 'cuisine', 'cafe', 'dishes', 'meal', 'delicious',
            'calories', 'spices', 'tbsp', 'cup', 'taste', 'bakery', 'dessert', 'baking'
        ],
        'subcategories': {
            'Recipe': ['recipe', 'ingredients', 'instructions', 'cook', 'tbsp', 'tablespoon', 'minutes'],
            'Food Order': ['swiggy', 'zomato', 'restaurant', 'delivered to', 'delivery partner', 'food item'],
            'Menu & Dining': ['menu', 'cafe', 'dishes', 'beverages', 'starters', 'main course']
        }
    },
    'Shopping': {
        'keywords': [
            'order confirmed', 'shipped', 'delivered', 'tracking', 'amazon', 'flipkart', 'myntra',
            'order id', 'return', 'warranty', 'refund', 'package', 'courier', 'item total',
            'shipping address', 'dispatch', 'clothes', 'footwear', 'apparel', 'shoes', 'dress'
        ],
        'subcategories': {
            'Order & Delivery': ['order confirmed', 'delivered', 'shipped', 'tracking', 'amazon', 'flipkart'],
            'Warranty & Return': ['warranty', 'return', 'replacement', 'refund', 'guarantee'],
            'Fashion & Clothes': ['clothes', 'footwear', 'apparel', 'shoes', 'shirt', 'dress', 'jeans']
        }
    },
    'Personal': {
        'keywords': [
            'diary', 'journal', 'health', 'doctor', 'prescription', 'medicine', 'family',
            'reminder', 'goal', 'workout', 'gym', 'fitness', 'clinic', 'hospital', 'dosage',
            'habits', 'routine', 'reflection', 'thought', 'personal'
        ],
        'subcategories': {
            'Health & Medical': ['prescription', 'doctor', 'medicine', 'clinic', 'hospital', 'dosage', 'health'],
            'Diary & Journal': ['diary', 'journal', 'dear diary', 'reflection', 'today i', 'memories'],
            'Goals & Fitness': ['workout', 'gym', 'fitness', 'routine', 'goal', 'habit']
        }
    }
}

def auto_categorize(title, content, tags=None, tm_label=None):
    text_combined = f"{title} {title} {title} {content}".lower()
    
    tm_bonus = {}
    if tm_label:
        tm_l = tm_label.lower()
        if 'food' in tm_l:
            tm_bonus['Food'] = 5
        elif 'cloth' in tm_l or 'footwear' in tm_l:
            tm_bonus['Shopping'] = 5
        elif 'cartoon' in tm_l:
            tm_bonus['Personal'] = 3

    scores = {}
    for cat, data in CATEGORY_RULES.items():
        score = tm_bonus.get(cat, 0)
        for kw in data['keywords']:
            matches = len(re.findall(r'\b' + re.escape(kw) + r'\b', text_combined))
            score += matches * 2
        scores[cat] = score

    best_cat, best_score = max(scores.items(), key=lambda x: x[1])
    
    if best_score < 3:
        return {'category': 'General', 'subcategory': '', 'confidence': 30}

    subcat_rules = CATEGORY_RULES.get(best_cat, {}).get('subcategories', {})
    best_subcat = ''
    best_sub_score = 0
    for sc, sc_kws in subcat_rules.items():
        sc_score = sum(len(re.findall(r'\b' + re.escape(k) + r'\b', text_combined)) for k in sc_kws)
        if sc_score > best_sub_score:
            best_sub_score = sc_score
            best_subcat = sc

    confidence = min(98, int(45 + min(best_score * 4, 50)))
    return {
        'category': best_cat,
        'subcategory': best_subcat,
        'confidence': confidence
    }
