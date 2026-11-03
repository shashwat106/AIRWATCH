"""General public guidance per CPCB category. Not medical advice."""

DISCLAIMER = "General guidance only, not medical advice. If you have symptoms or a health condition, ask a doctor."

ADVICE: dict[str, list[dict[str, str]]] = {
    "Good": [
        {"id": "mask", "title": "Mask", "text": "No mask needed for air quality."},
        {"id": "windows", "title": "Windows", "text": "Open windows and air out your home."},
        {"id": "kids", "title": "Children", "text": "Outdoor play is fine."},
        {"id": "exercise", "title": "Exercise", "text": "Any time of day suits outdoor exercise."},
    ],
    "Satisfactory": [
        {"id": "mask", "title": "Mask", "text": "Most people do not need a mask."},
        {"id": "windows", "title": "Windows", "text": "Fine to keep windows open."},
        {"id": "kids", "title": "Children", "text": "Outdoor play is fine. Watch children who are sensitive to air pollution."},
        {"id": "exercise", "title": "Exercise", "text": "Outdoor exercise is fine for most people."},
    ],
    "Moderately Polluted": [
        {"id": "mask", "title": "Mask", "text": "Consider an N95 for long periods outdoors if you are sensitive."},
        {"id": "windows", "title": "Windows", "text": "Air out your home during the cleanest hours."},
        {"id": "kids", "title": "Children", "text": "Outdoor play is fine, with more breaks for sensitive children."},
        {"id": "exercise", "title": "Exercise", "text": "Choose the cleanest hours and ease off if you feel discomfort."},
    ],
    "Poor": [
        {"id": "mask", "title": "Mask", "text": "Wear a well-fitted N95 for longer periods outdoors."},
        {"id": "windows", "title": "Windows", "text": "Keep windows closed during the dirtiest hours."},
        {"id": "kids", "title": "Children", "text": "Shorten outdoor play and keep it to the cleanest hours."},
        {"id": "exercise", "title": "Exercise", "text": "Move hard exercise indoors or to the cleanest hours."},
    ],
    "Very Poor": [
        {"id": "mask", "title": "Mask", "text": "Wear a well-fitted N95 whenever you are outdoors."},
        {"id": "windows", "title": "Windows", "text": "Keep windows closed. Use an air purifier if you have one."},
        {"id": "kids", "title": "Children", "text": "Keep play indoors where you can."},
        {"id": "exercise", "title": "Exercise", "text": "Avoid outdoor exercise. Exercise indoors instead."},
    ],
    "Severe": [
        {"id": "mask", "title": "Mask", "text": "Go out only if you need to, and wear a well-fitted N95."},
        {"id": "windows", "title": "Windows", "text": "Keep windows and doors closed. Run an air purifier if you have one."},
        {"id": "kids", "title": "Children", "text": "Keep children indoors."},
        {"id": "exercise", "title": "Exercise", "text": "Skip outdoor exercise and keep indoor exercise light."},
    ],
}
