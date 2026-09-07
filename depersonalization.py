"""Centralized bearer-token response depersonalization helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from russian_given_names import GIVEN_NAMES


REDACTED_PHONE = "[redacted-phone]"
REDACTED_EMAIL = "[redacted-email]"
REDACTED_NAME = "[redacted-name]"
REDACTED_ADDRESS = "[redacted-address]"

# Stage 275: report columns are named by generated SQL from a Russian request,
# so the dictionary had to learn Russian. Only qualified names are listed here:
# a bare "имя" is as often a pet's or a product's as a person's, and redacting
# those would quietly ruin the report instead of protecting anyone.
_NAME_KEYS = frozenset({
    "name",
    "firstname",
    "lastname",
    "middlename",
    "fio",
    "clientname",
    "ownername",
    # Этап 308: оба ключа уходили наружу целиком. `doctorname` — ФИО врача в
    # плоских строках (`get_inactive_pets`), `contactperson` — контактное лицо
    # поставщика. Те же имена через `get_users` маскировались, то есть
    # обещание режима исполнялось непоследовательно.
    "doctorname",
    "username",
    "contactperson",
    "client",
    "owner",
    "фио",
    "владелец",
    "владелецпитомца",
    "хозяин",
    "клиент",
    "имяклиента",
    "имявладельца",
    "фамилия",
    "отчество",
    "фамилияимяотчество",
    "полноеимя",
    "контактноелицо",
})
_PHONE_KEYS = frozenset({
    "phone",
    "cellphone",
    "homephone",
    "workphone",
    "ownerphone",
    "doctorphone",
    "телефон",
    "телефонклиента",
    "телефонвладельца",
    "мобильный",
    "мобильныйтелефон",
    "контактныйтелефон",
    "номертелефона",
})
_EMAIL_KEYS = frozenset({"email", "mail", "почта", "электроннаяпочта", "емейл", "имейл"})
_ADDRESS_KEYS = frozenset({"address", "адрес", "адресклиента", "адресдоставки"})
# Этап 308. Кто такой владелец записи — по ключу, под которым она пришла.
# Формы ответов не единообразны, и правила «взять соседний id» не хватает:
# `debtors` не совпадает с названием сущности, а у владельца, вложенного в
# питомца, своего `id` нет вовсе.
_NOT_A_PERSON = object()

_ENTITY_BY_KEY: dict[str, object] = {
    "client": "client", "clients": "client", "debtors": "client",
    "inactiveclients": "client", "owner": "client",
    "user": "user", "users": "user", "doctor": "user",
    "pet": "pet", "pets": "pet", "inactivepets": "pet", "patient": "pet",
    "supplier": "supplier", "suppliers": "supplier",
    # Записи, в которых `name` и контакты не принадлежат человеку. Сегодня они
    # маскируются зря: название вакцины и телефон филиала — не ПДн.
    "vaccination": _NOT_A_PERSON, "vaccinations": _NOT_A_PERSON,
    "role": _NOT_A_PERSON, "roles": _NOT_A_PERSON,
    "type": _NOT_A_PERSON, "types": _NOT_A_PERSON,
    "pettype": _NOT_A_PERSON, "pettypes": _NOT_A_PERSON,
    "breed": _NOT_A_PERSON, "breeds": _NOT_A_PERSON,
    "good": _NOT_A_PERSON, "goods": _NOT_A_PERSON,
    "goodgroup": _NOT_A_PERSON, "goodgroups": _NOT_A_PERSON,
    "unit": _NOT_A_PERSON, "units": _NOT_A_PERSON,
    "diagnosis": _NOT_A_PERSON, "diagnoses": _NOT_A_PERSON,
    "clinic": _NOT_A_PERSON, "clinics": _NOT_A_PERSON,
    "city": _NOT_A_PERSON, "cities": _NOT_A_PERSON,
    "street": _NOT_A_PERSON, "streets": _NOT_A_PERSON,
}

# Вложенная запись без собственного `id`: идентификатор лежит в родителе.
_NESTED_ID_IN_PARENT = {
    "owner": ("owner_id", "client_id"),
    "client": ("client_id",),
    "patient": ("patient_id", "pet_id"),
    "doctor": ("doctor_id", "user_id"),
}

# Поле, чей владелец — не та запись, в которой оно лежит. Строка
# `inactive_pets[]` несёт питомца, клиента и сотрудника разом.
_FIELD_ADDRESS: dict[str, tuple[str, tuple[str, ...]]] = {
    "ownername": ("client", ("owner_id", "client_id")),
    "ownerphone": ("client", ("owner_id", "client_id")),
    "owner": ("client", ("owner_id", "client_id")),
    "clientname": ("client", ("client_id",)),
    "client": ("client", ("client_id",)),
    "doctorname": ("user", ("doctor_id", "user_id")),
    "doctorphone": ("user", ("doctor_id", "user_id")),
    "username": ("user", ("user_id",)),
}

# Ключи, персональные только внутри своей записи. `nickname` у сотрудника —
# такой же идентификатор человека, как ФИО рядом; у кого-то ещё — нет.
_ENTITY_ONLY_KEYS = {"nickname": "user"}

_PLACEHOLDER_FIELD_RE = re.compile(r"^[a-z0-9_]+$")

_FREE_TEXT_KEYS = frozenset({
    "description",
    "diagnos",
    "diagnosis",
    "diagnostext",
    "diagnostypetext",
    "recomendation",
    "recommendation",
    "treatment",
    "comment",
    "note",
    "notes",
    "deathnote",
})

_EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b")
_DATE_OR_DATETIME_RE = re.compile(
    r"(?<!\d)(?:"
    r"(?:19\d{2}|20\d{2}|2100)-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
    r"|(?:0[1-9]|[12]\d|3[01])\.(?:0[1-9]|1[0-2])\.(?:19\d{2}|20\d{2}|2100)"
    r")(?:[T\s](?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):?[0-5]\d)?)?(?!\d)"
)
_PHONE_RE = re.compile(r"(?<!\[redacted-phone\])(?:\+?\d[\d\-\s().]{8,}\d)")
_OWNER_PHRASE_RE = re.compile(
    r"(?u)\b(?i:(?:владелец|хозяин|owner))\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё.\-]+(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё.\-]+){0,2}"
)
# `Иванов И. И.`, `Иванов И.И.` and the dotless `Иванов И И` that a report
# column produces just as often.
_INITIALS_RE = re.compile(
    r"(?u)\b[A-ZА-ЯЁ][a-zа-яё]{1,30}\s+[A-ZА-ЯЁ]\.?\s?[A-ZА-ЯЁ]\.?(?![a-zа-яё])"
)
# Stage 275: three words in a row that look like a name. Two would catch a
# clinic or a street just as often as a person, so the two-word form is left
# to the other layers on purpose.
#
# Latin-aware and case-aware, but NOT case-insensitive.
#
# Stage 275 wrote this rule with a plain `(?i)` to catch `ИВАНОВ ПЕТР
# СЕРГЕЕВИЧ` and `Ivanov Petr Sergeevich`. The flag did catch them — and it
# also turned `[А-ЯЁA-Z]` into "any letter", so every three ordinary words in a
# row became a name: `Стрижка когтей собаке` and `Анализ крови общий` came back
# as `[redacted-name]`. Found 01.09.2026, in production the whole time.
#
# The forms are spelled out instead: title case or all caps, in either script.
# A name is written that way; a sentence is not.
# One definition of "a word a name is made of", used by every rule below. It
# has to allow what surnames actually contain — an inner hyphen, an apostrophe,
# an inner capital — or the rule matches only the tail: `Петров-Водкин Пётр
# Сергеевич` came back as `Петров-[redacted-name]`, leaving half a surname and
# a broken value behind (found by review, 01.09.2026).
_NAME_PART = r"(?:[А-ЯЁ][А-ЯЁа-яё]{1,30}|[A-Z][A-Za-z]{1,30})"
_NAME_TAIL = r"(?:[А-ЯЁ][А-ЯЁа-яё]{0,30}|[A-Z][A-Za-z]{0,30}|[а-яё]{1,30}|[a-z]{1,30})"
# `O'Connor` and `Д'Артаньян` start with a single letter before the apostrophe,
# which the general form cannot allow — a lone capital would turn `А Б В` into
# a name.
_NAME_WORD = rf"(?:[А-ЯЁA-Z]'{_NAME_PART}|{_NAME_PART}(?:['\-]{_NAME_TAIL})*)"
_FULL_NAME_RE = re.compile(
    rf"(?u)\b{_NAME_WORD}\s+{_NAME_WORD}\s+{_NAME_WORD}\b"
)
# A patronymic gives a person away on its own: `-ович`, `-евна` and their kin
# are almost never part of a product or a clinic name, so a two-word "Пётр
# Сергеевич" is caught here even though a bare two-word name is not.
_PATRONYMIC_RE = re.compile(
    r"(?u)\b[А-ЯЁ][а-яёА-ЯЁ]{1,30}\s+[А-ЯЁ][а-яёА-ЯЁ]*?"
    r"(?i:ович|евич|ич|овна|евна|ична|инична)\b"
)
# A value that names a street is an ordinary analytical dimension. Checked
# after the address rule has had its turn, so a real address is already gone by
# then and only a bare street name is left to protect from the name rules.
_STREET_MARKER_RE = re.compile(
    r"(?ui)\b(?:ул\.|улица|пр-?т|проспект|пер\.|переулок|ш\.|шоссе|б-р|бульвар)"
)
# A postal address written out. Anchored on the parts that only an address has
# — city, street, building, flat — so a service name cannot match by accident.
# A postal address, not a street name. The house or flat part is required: a
# report grouped by street is a normal analytical dimension, and redacting
# `улица Красных Партизан` would delete the answer rather than protect anyone.
_ADDRESS_RE = re.compile(
    r"(?ui)(?:\bг\.\s?[А-ЯЁ][а-яё\-]+[,\s]+)?"
    r"(?:ул\.|улица|пр-?т|проспект|пер\.|переулок|ш\.|шоссе|б-р|бульвар)\s?[А-ЯЁа-яё0-9\-\s.]{2,40}?"
    r"[,\s]+д\.?\s?\d+[А-Яа-я]?(?:[,\s]+(?:кв\.?|оф\.?)\s?\d+)?"
)
# A run of digits that could be a Russian phone number. Bounded on purpose: a
# pet's microchip is fifteen digits and a barcode thirteen, and a report that
# loses those is broken rather than private.
_PHONE_LIKE_RE = re.compile(r"(?<![\d\-])\+?\d[\d\-\s().]{7,18}\d(?![\d\-])")
# Stage 277. Words that make a capitalised pair something other than a person.
# Checked on the pair itself, not on the whole value: a marker at the start of a
# comment must not switch the protection off for the name at its end.
_MARKER_WORDS = frozenset({
    # legal forms
    "ооо", "зао", "пао", "ао", "нко", "ано", "ип", "пк", "фгбу", "гбу", "муп",
    "llc", "ltd", "inc",
    # organisations
    "клиника", "ветклиника", "аптека", "центр", "госпиталь", "лаборатория",
    "сеть", "филиал", "отделение", "clinic", "pharma",
    # saints and holidays
    "святой", "святая", "преподобный", "блаженный", "день",
})
# Place words also block the pair that follows them: a street really is named
# by what comes after the word `улица`, so one step back is honest here. No
# such step for organisations — after `Ветклиника` there can be a name or a
# person, and erring toward a leak is not allowed.
_PLACE_WORDS = frozenset({
    "улица", "ул", "проспект", "пр", "переулок", "пер", "шоссе", "бульвар",
    "площадь", "сквер", "парк", "поселок", "село", "деревня", "станция",
    "район", "микрорайон", "город", "г",
})
# A commercial tail is a tail. `Вера Плюс` is a name of a business; `Vet Petr`
# is a person, and the only difference is where the marker stands. Letting such
# a word stand first would make it a shield for real names.
_TAIL_WORDS = frozenset({
    "плюс", "люкс", "сервис", "групп", "трейд", "фарм", "вет", "эконом",
    "премиум", "plus", "group", "vet",
})
_PAIR_WORD_RE = re.compile(r"(?u)[^\W\d_]+(?:['\-][^\W\d_]+)*")
# Stage 277: the one lowercase form worth taking. Requiring capitals is what
# keeps `вялый паралич` out of the patronymic rule, so lowercase is allowed
# here only when the first word is a known given name — `петр сергеевич` is a
# person, `вялый паралич` is a diagnosis, and the dictionary knows which.
_LOWER_PATRONYMIC_RE = re.compile(
    r"(?ui)\b([^\W\d_]{2,31})\s+([^\W\d_]*?(?:ович|евич|овна|евна|ична|инична))\b"
)
_SOFT_PUNCTUATION = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    "\u2018": "'", "\u2019": "'", "\u02bc": "'",
}


def _fold(word: str) -> str:
    return word.lower().replace("ё", "е")


def _is_given_name(word: str) -> bool:
    folded = _fold(word)
    if folded in GIVEN_NAMES:
        return True
    return any(part in GIVEN_NAMES for part in folded.split("-") if part)


def _starts_capitalised(word: str) -> bool:
    head = word[0]
    return head.isupper() or (word.isupper() and head.isalpha())


def _blocks_pair(word: str, *, is_second: bool) -> bool:
    folded = _fold(word)
    if folded in _MARKER_WORDS or folded in _PLACE_WORDS:
        return True
    return is_second and folded in _TAIL_WORDS


def _normalize_soft_punctuation(text: str) -> str:
    for source, target in _SOFT_PUNCTUATION.items():
        text = text.replace(source, target)
    return text


def redact_given_name_pairs(text: str) -> str:
    """Redact a capitalised pair when one of its words is a known given name.

    Stage 277, the form stage 275 could not take. Overlapping pairs are all
    considered: in `ООО Вера Иванова` the first pair is blocked by the legal
    form and the second is not, and a scanner that consumed the first would
    never look at the second.
    """
    words = [(match.start(), match.end(), match.group(0)) for match in _PAIR_WORD_RE.finditer(text)]
    spans: list[tuple[int, int]] = []
    for index in range(len(words) - 1):
        left_start, left_end, left = words[index]
        right_start, right_end, right = words[index + 1]
        separator = text[left_end:right_start]
        if not separator or separator.strip():
            continue
        if not (_starts_capitalised(left) and _starts_capitalised(right)):
            continue
        if _blocks_pair(left, is_second=False) or _blocks_pair(right, is_second=True):
            continue
        if index and _fold(words[index - 1][2]) in _PLACE_WORDS:
            continue
        if not (_is_given_name(left) or _is_given_name(right)):
            continue
        spans.append((left_start, right_end))

    if not spans:
        return text
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    parts: list[str] = []
    position = 0
    for start, end in merged:
        parts.append(text[position:start])
        parts.append(REDACTED_NAME)
        position = end
    parts.append(text[position:])
    return "".join(parts)


def _normalize_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


def _positive_id(value: object) -> int | None:
    """Идентификатор приходит от апстрима — в адрес пускаем только целое > 0.

    Плейсхолдер разбирают регексом на стороне приложения: чужое двоеточие или
    скобка сломали бы разбор, а не просто выглядели плохо.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _placeholder_field(key: str) -> str | None:
    """Сегмент имени поля — имя колонки ответа, а не ключ классификатора.

    `_normalize_key` выбрасывает подчёркивания (`last_name` → `lastname`) и
    для адреса не годится: приложение резолвит по тому имени, которое видит.
    Русский ключ адресом стать не может — падаем на необратимую маску.
    """
    candidate = key.strip().lower()
    return candidate if _PLACEHOLDER_FIELD_RE.match(candidate) else None


def _record_address(
    mapping: Mapping, *, key: str | None, inherited: tuple | None, parent: Mapping | None
) -> tuple | None:
    """Чья это запись и какой у неё идентификатор."""
    entity = _ENTITY_BY_KEY.get(_normalize_key(key or "")) if key else None
    if entity is None:
        return inherited
    if entity is _NOT_A_PERSON:
        return (_NOT_A_PERSON, None)
    record_id = _positive_id(mapping.get("id"))
    if record_id is None and isinstance(parent, Mapping):
        for parent_field in _NESTED_ID_IN_PARENT.get(_normalize_key(key or ""), ()):
            record_id = _positive_id(parent.get(parent_field))
            if record_id is not None:
                break
    return (entity, record_id)


def _addressed_placeholder(
    key: str, *, record: Mapping | None, address: tuple | None
) -> str | None:
    """`[сущность:id:поле]` — или None, если адресовать нечем."""
    override = _FIELD_ADDRESS.get(_normalize_key(key))
    if override is not None and isinstance(record, Mapping):
        entity, id_fields = override
        record_id = next(
            (found for field in id_fields if (found := _positive_id(record.get(field)))),
            None,
        )
    elif address is not None:
        entity, record_id = address
    else:
        return None
    if not isinstance(entity, str) or record_id is None:
        return None
    field = _placeholder_field(key)
    return f"[{entity}:{record_id}:{field}]" if field else None


def _redaction_for_key(key: str, *, entity: object = None) -> str | None:
    normalized = _normalize_key(key)
    required_entity = _ENTITY_ONLY_KEYS.get(normalized)
    if required_entity is not None:
        return REDACTED_NAME if entity == required_entity else None
    if normalized in _NAME_KEYS:
        return REDACTED_NAME
    if normalized in _PHONE_KEYS:
        return REDACTED_PHONE
    if normalized in _EMAIL_KEYS:
        return REDACTED_EMAIL
    if normalized in _ADDRESS_KEYS:
        return REDACTED_ADDRESS
    return None


def _is_free_text_key(key: str) -> bool:
    return _normalize_key(key) in _FREE_TEXT_KEYS


def sanitize_text(text: str) -> str:
    """Scrub only explicit PII patterns from whitelist free-text fields."""
    if not text:
        return text
    date_spans = [match.span() for match in _DATE_OR_DATETIME_RE.finditer(text)]
    email_spans = [match.span() for match in _EMAIL_RE.finditer(text)]
    redactions = [(start, end, REDACTED_EMAIL) for start, end in email_spans]
    for phone_match in _PHONE_RE.finditer(text):
        start, end = phone_match.span()
        if any(
            date_start <= start and end <= date_end
            for date_start, date_end in date_spans
        ):
            continue
        date_free = _DATE_OR_DATETIME_RE.sub("", text[start:end])
        if not any(char.isdigit() for char in date_free):
            continue

        phone_fragments = [(start, end)]
        for email_start, email_end in email_spans:
            fragments_without_email: list[tuple[int, int]] = []
            for fragment_start, fragment_end in phone_fragments:
                if fragment_end <= email_start or fragment_start >= email_end:
                    fragments_without_email.append((fragment_start, fragment_end))
                    continue
                if fragment_start < email_start:
                    fragments_without_email.append((fragment_start, email_start))
                if email_end < fragment_end:
                    fragments_without_email.append((email_end, fragment_end))
            phone_fragments = fragments_without_email
        redactions.extend(
            (fragment_start, fragment_end, REDACTED_PHONE)
            for fragment_start, fragment_end in phone_fragments
        )

    sanitized_parts: list[str] = []
    position = 0
    for start, end, replacement in sorted(redactions, key=lambda item: (item[0], -item[1])):
        if start < position:
            continue
        sanitized_parts.append(text[position:start])
        sanitized_parts.append(replacement)
        position = end
    sanitized_parts.append(text[position:])
    sanitized = "".join(sanitized_parts)
    sanitized = _OWNER_PHRASE_RE.sub(lambda _m: f"owner {REDACTED_NAME}", sanitized)
    sanitized = _INITIALS_RE.sub(REDACTED_NAME, sanitized)
    return sanitized


def sanitize_report_value(text: str) -> str:
    """Clean a value from a report, whatever column it arrived in.

    Stage 275, layer two. A generated report names its columns itself, so the
    column name cannot be relied on; what is left is the value. Emails and
    phone-shaped numbers are recognisable enough to remove outright. Names are
    only taken in the forms that cannot be mistaken for a company or a street:
    three capitalised words, or a surname with initials.
    """
    if not text:
        return text
    cleaned = _normalize_soft_punctuation(text)
    cleaned = _EMAIL_RE.sub(REDACTED_EMAIL, cleaned)
    # The address goes first so that what remains can be judged on its own: a
    # leftover street marker then means a street name, not an address.
    cleaned = _ADDRESS_RE.sub(REDACTED_ADDRESS, cleaned)
    if not _STREET_MARKER_RE.search(cleaned):
        cleaned = _FULL_NAME_RE.sub(REDACTED_NAME, cleaned)
        cleaned = _PATRONYMIC_RE.sub(REDACTED_NAME, cleaned)
        cleaned = _INITIALS_RE.sub(REDACTED_NAME, cleaned)

    # Stage 277 stands outside the street guard on purpose: it carries its own,
    # which looks at the pair rather than at the whole value.
    cleaned = redact_given_name_pairs(cleaned)
    cleaned = _LOWER_PATRONYMIC_RE.sub(
        lambda match: REDACTED_NAME if _is_given_name(match.group(1)) else match.group(0),
        cleaned,
    )

    date_spans = [match.span() for match in _DATE_OR_DATETIME_RE.finditer(cleaned)]

    def _replace_phone(match: re.Match) -> str:
        start, end = match.span()
        # A date is digits and separators too: `2026-08-31 10:11` counts ten of
        # them, and a report stripped of its dates is worse than useless.
        if any(start < date_end and date_start < end for date_start, date_end in date_spans):
            return match.group(0)
        digits = [char for char in match.group(0) if char.isdigit()]
        # Ten and eleven digits is what a Russian phone has; anything longer is
        # a chip, a barcode or an internal identifier.
        return REDACTED_PHONE if 10 <= len(digits) <= 11 else match.group(0)

    return _PHONE_LIKE_RE.sub(_replace_phone, cleaned)


def sanitize_report_cell(column: str, value: str) -> str:
    """Clean one report cell the way a report row is cleaned.

    Stage 276: a CSV export is a report with its column names in the header
    row. Same two layers, same order — the name decides first, then the value.
    """
    return _sanitize_value(value, key=column or None, report_mode=True)


def sanitize_tool_result(payload: Any, *, report_mode: bool = False) -> Any:
    """Recursively sanitize structured fields and whitelist free-text fields.

    `report_mode` turns on the value-level cleaning that report rows need and
    ordinary tools must not get: their fields are predictable, and scrubbing
    every value there would cost real data for no gain.
    """
    return _sanitize_value(payload, report_mode=report_mode)


def _sanitize_value(
    value: Any,
    *,
    key: str | None = None,
    report_mode: bool = False,
    address: tuple | None = None,
    record: Mapping | None = None,
) -> Any:
    """`address` — чья запись сейчас разбирается, `record` — сама запись.

    Этап 308: без этих двух маска не может сказать, о ком речь. `address`
    наследуется вложенными значениями, `record` нужен полям, чей владелец —
    не та запись, в которой они лежат (`doctor_name` внутри строки о питомце).
    """
    if isinstance(value, Mapping):
        child_address = _record_address(value, key=key, inherited=address, parent=record)
        return {
            child_key: _sanitize_value(
                child_value,
                key=str(child_key),
                report_mode=report_mode,
                address=child_address,
                record=value,
            )
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_value(
                item, key=key, report_mode=report_mode, address=address, record=record
            )
            for item in value
        ]
    if not isinstance(value, str):
        return value

    entity = address[0] if address else None
    if entity is _NOT_A_PERSON:
        # Название вакцины, роли, породы, телефон филиала — не персональные
        # данные, и маскировать их значит терять данные без выигрыша.
        return value
    if key:
        replacement = _redaction_for_key(key, entity=entity)
        if replacement is not None:
            return _addressed_placeholder(key, record=record, address=address) or replacement
        if _is_free_text_key(key):
            # Адресности здесь нет намеренно: найденное внутри текста ФИО может
            # принадлежать владельцу, врачу или третьему лицу, и адрес записи о
            # нём ничего не говорит.
            return sanitize_text(value)
    if report_mode:
        return sanitize_report_value(value)
    return value
