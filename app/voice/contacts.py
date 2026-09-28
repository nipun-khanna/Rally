"""Resolve an explicitly requested contact locally, without guessing a number."""

from app.voice.caller import extract_phone


def _name(value):
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


class LocalContactLookup:
    def __init__(self, fetch_contacts):
        self.fetch_contacts = fetch_contacts

    def __call__(self, requested):
        query = _name(requested)
        try:
            contacts = self.fetch_contacts()
        except Exception:
            raise ValueError("local contacts are unavailable; please give me the phone number") from None
        exact, given = [], []
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
            full = _name(" ".join(str(contact.get(k) or "") for k in ("firstName", "lastName")))
            display = _name(contact.get("displayName"))
            identity = full or display
            if not identity:
                continue
            item = (identity, contact)
            if query and query in {full, display}:
                exact.append(item)
            elif query and query == _name(contact.get("firstName")):
                given.append(item)
        matches = exact or given
        if len({identity for identity, _ in matches}) > 1:
            raise ValueError(f"I found multiple contacts named {requested}; please give me the full name or phone number")
        numbers = set()
        for _, contact in matches:
            for phone in contact.get("phoneNumbers") or []:
                address = phone.get("address") if isinstance(phone, dict) else phone
                number = extract_phone(address) if isinstance(address, str) else ""
                if number:
                    numbers.add(number)
        if len(numbers) > 1:
            raise ValueError(f"I found multiple numbers for {requested}; which phone number should I call?")
        if not numbers:
            raise ValueError(f"I don't have a phone number for {requested}; what number should I call?")
        return next(iter(numbers))
