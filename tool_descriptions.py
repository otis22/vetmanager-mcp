from fastmcp import FastMCP


ENTITY_METADATA: dict[str, dict[str, str | list[str]]] = {
    "client": {
        "singular": "client / owner record",
        "plural": "client / owner records",
        "synonyms": [
            "клиент",
            "владелец",
            "хозяин",
            "хозяин питомца",
            "контакт",
            "клиентская база",
            "client",
        ],
    },
    "pet": {
        "singular": "pet / patient record",
        "plural": "pet / patient records",
        "synonyms": [
            "питомец",
            "пациент",
            "животное",
            "кот",
            "собака",
            "пациент клиники",
            "pet",
            "animal",
        ],
    },
    "admission": {
        "singular": "admission / appointment record",
        "plural": "admission / appointment records",
        "synonyms": [
            "приём",
            "визит",
            "запись",
            "запись на приём",
            "запись к врачу",
            "консультация",
            "appointment",
        ],
    },
    "medical_card": {
        "singular": "medical card / clinical record",
        "plural": "medical card / clinical records",
        "synonyms": [
            "медкарта",
            "медицинская карта",
            "история болезни",
            "история лечения",
            "клиническая запись",
            "осмотр",
            "medical card",
            "medical record",
        ],
    },
    "vaccination": {
        "singular": "vaccination record",
        "plural": "vaccination records",
        "synonyms": [
            "вакцинация",
            "прививка",
            "прививочная карта",
            "история вакцинаций",
            "vaccination card",
            "vaccine record",
        ],
    },
    "invoice": {
        "singular": "invoice / bill record",
        "plural": "invoice / bill records",
        "synonyms": [
            "счёт",
            "счёт-фактура",
            "чек",
            "квитанция",
            "документ оплаты",
            "invoice",
            "bill",
        ],
    },
    "invoice_document": {
        "singular": "invoice line item",
        "plural": "invoice line items",
        "synonyms": [
            "позиция счёта",
            "строка счёта",
            "товар в счёте",
            "услуга в счёте",
            "позиция",
            "invoice document",
            "invoice line",
        ],
    },
    "good": {
        "singular": "good / service catalog item",
        "plural": "good / service catalog items",
        "synonyms": [
            "товар",
            "услуга",
            "позиция прайса",
            "препарат",
            "лекарство",
            "корм",
            "расходник",
            "номенклатура",
            "good",
            "service",
            "item",
        ],
    },
    "user": {
        "singular": "staff / user record",
        "plural": "staff / user records",
        "synonyms": [
            "сотрудник",
            "пользователь",
            "врач",
            "ветеринар",
            "доктор",
            "администратор",
            "персонал",
            "user",
            "staff",
            "employee",
        ],
    },
    "breed": {
        "singular": "breed reference record",
        "plural": "breed reference records",
        "synonyms": [
            "порода",
            "порода животного",
            "порода питомца",
            "порода собаки",
            "порода кошки",
            "breed",
        ],
    },
    "pet_type": {
        "singular": "pet type reference record",
        "plural": "pet type reference records",
        "synonyms": [
            "вид животного",
            "тип животного",
            "вид",
            "тип питомца",
            "pet type",
        ],
    },
    "city": {
        "singular": "city reference record",
        "plural": "city reference records",
        "synonyms": ["город", "населённый пункт", "city"],
    },
    "city_type": {
        "singular": "city type reference record",
        "plural": "city type reference records",
        "synonyms": [
            "тип населённого пункта",
            "тип города",
            "вид населённого пункта",
        ],
    },
    "street": {
        "singular": "street reference record",
        "plural": "street reference records",
        "synonyms": ["улица", "адрес", "street"],
    },
    "unit": {
        "singular": "unit reference record",
        "plural": "unit reference records",
        "synonyms": ["единица измерения", "ед. изм.", "единица", "unit"],
    },
    "role": {
        "singular": "role / access level record",
        "plural": "role / access level records",
        "synonyms": [
            "роль",
            "роль пользователя",
            "права доступа",
            "уровень доступа",
            "role",
        ],
    },
    "user_position": {
        "singular": "staff position record",
        "plural": "staff position records",
        "synonyms": [
            "должность",
            "должность сотрудника",
            "специальность",
            "профессия",
            "user position",
        ],
    },
    "combo_manual_name": {
        "singular": "custom dictionary type",
        "plural": "custom dictionary types",
        "synonyms": [
            "справочник",
            "пользовательский справочник",
            "тип справочника",
            "классификатор",
            "combo manual",
        ],
    },
    "combo_manual_item": {
        "singular": "custom dictionary item",
        "plural": "custom dictionary items",
        "synonyms": [
            "элемент справочника",
            "значение справочника",
            "пункт справочника",
            "справочное значение",
            "combo item",
        ],
    },
    "payment": {
        "singular": "payment record",
        "plural": "payment records",
        "synonyms": [
            "оплата",
            "платёж",
            "внесение средств",
            "приход денег",
            "payment",
        ],
    },
    "closing_of_invoices": {
        "singular": "invoice closing / payment application record",
        "plural": "invoice closing / payment application records",
        "synonyms": [
            "закрытие счёта",
            "оплата счёта",
            "проведение оплаты",
            "привязка платежа к счёту",
            "применение платежа",
        ],
    },
    "cassa": {
        "singular": "cash register record",
        "plural": "cash register records",
        "synonyms": [
            "касса",
            "кассовый аппарат",
            "кассовый узел",
            "точка продаж",
            "POS",
            "cash register",
        ],
    },
    "cassa_close": {
        "singular": "cash register closing record",
        "plural": "cash register closing records",
        "synonyms": [
            "закрытие кассы",
            "закрытие смены",
            "Z-отчёт",
            "инкассация",
            "закрытие кассовой смены",
        ],
    },
    "good_group": {
        "singular": "good / service group",
        "plural": "good / service groups",
        "synonyms": [
            "группа товаров",
            "группа услуг",
            "категория товаров",
            "категория услуг",
            "раздел прайса",
            "папка товаров",
            "good group",
        ],
    },
    "good_sale_param": {
        "singular": "pricing parameter record",
        "plural": "pricing parameter records",
        "synonyms": [
            "параметры продажи",
            "цена товара",
            "цена услуги",
            "прайс",
            "ценообразование",
            "наценка",
            "good sale param",
        ],
    },
    "party_account": {
        "singular": "inventory batch record",
        "plural": "inventory batch records",
        "synonyms": [
            "партия",
            "партия товара",
            "серия",
            "лот",
            "поступление",
            "party account",
        ],
    },
    "party_account_doc": {
        "singular": "inventory batch movement line",
        "plural": "inventory batch movement lines",
        "synonyms": [
            "строка складского документа",
            "позиция накладной",
            "движение партии",
            "party account doc",
        ],
    },
    "store_document": {
        "singular": "warehouse document",
        "plural": "warehouse documents",
        "synonyms": [
            "складской документ",
            "накладная",
            "приходная накладная",
            "расходная накладная",
            "акт списания",
            "складская операция",
            "store document",
        ],
    },
    "supplier": {
        "singular": "supplier / counterparty record",
        "plural": "supplier / counterparty records",
        "synonyms": [
            "поставщик",
            "контрагент",
            "поставщик товаров",
            "поставщик лекарств",
            "дистрибьютор",
            "supplier",
        ],
    },
    "hospital": {
        "singular": "hospitalization / inpatient record",
        "plural": "hospitalization / inpatient records",
        "synonyms": [
            "стационар",
            "госпитализация",
            "стационарное лечение",
            "стационарный пациент",
            "hospital",
        ],
    },
    "hospital_block": {
        "singular": "hospital block / cage record",
        "plural": "hospital block / cage records",
        "synonyms": [
            "блок стационара",
            "клетка",
            "бокс",
            "секция стационара",
            "место в стационаре",
            "hospital block",
        ],
    },
    "diagnosis": {
        "singular": "diagnosis reference record",
        "plural": "diagnosis reference records",
        "synonyms": [
            "диагноз",
            "диагнозы",
            "МКБ",
            "заболевание",
            "болезнь",
            "патология",
            "diagnosis",
        ],
    },
    "clinic": {
        "singular": "clinic / branch record",
        "plural": "clinic / branch records",
        "synonyms": [
            "клиника",
            "филиал",
            "ветеринарная клиника",
            "ветклиника",
            "ветеринарный центр",
            "отделение",
            "clinic",
        ],
    },
    "timesheet": {
        "singular": "schedule / shift record",
        "plural": "schedule / shift records",
        "synonyms": [
            "расписание",
            "график работы",
            "рабочий график",
            "смена",
            "рабочая смена",
            "расписание врача",
            "timesheet",
        ],
    },
    "property": {
        "singular": "system property / setting",
        "plural": "system properties / settings",
        "synonyms": [
            "свойства",
            "настройки программы",
            "системные настройки",
            "конфигурация",
            "properties",
        ],
    },
    "anonymous_client": {
        "singular": "anonymous client record",
        "plural": "anonymous client records",
        "synonyms": [
            "анонимный клиент",
            "анонимизированный клиент",
            "удалённый клиент",
            "клиент без данных",
        ],
    },
    "stock_balance": {
        "singular": "stock balance record",
        "plural": "stock balance records",
        "synonyms": [
            "остаток",
            "остаток на складе",
            "количество на складе",
            "наличие товара",
            "сколько осталось",
            "запас",
            "stock",
            "inventory",
        ],
    },
    "messages": {
        "singular": "in-app notification / message campaign",
        "plural": "in-app notification / message campaigns",
        "synonyms": [
            "уведомление",
            "рассылка",
            "сообщение в программу",
            "уведомление пользователям",
            "push в программу",
            "messages",
        ],
    },
}


TOOL_ENTITY_MAP: dict[str, str] = {
    "get_clients": "client",
    "get_debtors": "client",
    "get_client_by_id": "client",
    "create_client": "client",
    "update_client": "client",
    "get_client_profile": "client",
    "get_pets": "pet",
    "get_pet_by_id": "pet",
    "create_pet": "pet",
    "update_pet": "pet",
    "get_pet_profile": "pet",
    "get_admissions": "admission",
    "get_admission_by_id": "admission",
    "create_admission": "admission",
    "update_admission": "admission",
    "get_medical_cards": "medical_card",
    "get_medical_cards_by_client_id": "medical_card",
    "get_medical_card_by_id": "medical_card",
    "create_medical_card": "medical_card",
    "update_medical_card": "medical_card",
    "get_vaccinations": "vaccination",
    "get_invoices": "invoice",
    "get_average_invoice": "invoice",
    "get_invoice_by_id": "invoice",
    "create_invoice": "invoice",
    "get_goods": "good",
    "get_good_by_id": "good",
    "get_users": "user",
    "get_user_by_id": "user",
    "get_breeds": "breed",
    "get_breed_by_id": "breed",
    "get_pet_types": "pet_type",
    "get_pet_type_by_id": "pet_type",
    "get_cities": "city",
    "get_city_by_id": "city",
    "get_city_types": "city_type",
    "get_streets": "street",
    "get_street_by_id": "street",
    "get_units": "unit",
    "get_unit_by_id": "unit",
    "get_roles": "role",
    "get_role_by_id": "role",
    "get_user_positions": "user_position",
    "get_user_position_by_id": "user_position",
    "get_combo_manual_names": "combo_manual_name",
    "get_combo_manual_name_by_id": "combo_manual_name",
    "get_combo_manual_items": "combo_manual_item",
    "get_combo_manual_item_by_id": "combo_manual_item",
    "get_payments": "payment",
    "get_payment_by_id": "payment",
    "create_payment": "payment",
    "get_closing_of_invoices": "closing_of_invoices",
    "get_closing_of_invoice_by_id": "closing_of_invoices",
    "get_invoice_documents": "invoice_document",
    "get_invoice_document_by_id": "invoice_document",
    "add_invoice_document": "invoice_document",
    "get_cassas": "cassa",
    "get_cassa_by_id": "cassa",
    "get_cassa_closes": "cassa_close",
    "get_cassa_close_by_id": "cassa_close",
    "get_good_groups": "good_group",
    "get_good_group_by_id": "good_group",
    "get_good_sale_params": "good_sale_param",
    "get_good_sale_param_by_id": "good_sale_param",
    "get_party_accounts": "party_account",
    "get_party_account_by_id": "party_account",
    "get_party_account_docs": "party_account_doc",
    "get_party_account_doc_by_id": "party_account_doc",
    "get_store_documents": "store_document",
    "get_store_document_by_id": "store_document",
    "get_suppliers": "supplier",
    "get_supplier_by_id": "supplier",
    "get_good_stock_balance": "stock_balance",
    "send_message_to_all": "messages",
    "send_message_to_users": "messages",
    "get_message_reports": "messages",
    "send_message_to_roles": "messages",
    "get_hospitalizations": "hospital",
    "get_hospitalization_by_id": "hospital",
    "create_hospitalization": "hospital",
    "get_hospital_blocks": "hospital_block",
    "get_hospital_block_by_id": "hospital_block",
    "get_diagnoses": "diagnosis",
    "get_clinics": "clinic",
    "get_clinic_by_id": "clinic",
    "get_timesheets": "timesheet",
    "get_timesheet_by_id": "timesheet",
    "get_properties": "property",
    "get_anonymous_clients": "anonymous_client",
    "delete_client": "client",
    "delete_pet": "pet",
    "update_invoice": "invoice",
    "delete_invoice": "invoice",
    "create_good": "good",
    "update_good": "good",
    "update_user": "user",
    "delete_invoice_document": "invoice_document",
    "create_supplier": "supplier",
    "update_supplier": "supplier",
    "update_hospitalization": "hospital",
    "create_timesheet": "timesheet",
}


SPECIAL_TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_debtors": (
        "Find ACTIVE debtors among client / owner records and return those with a "
        "negative balance. Use when the user asks for debtors, balances due, "
        "owing clients, or clients in debt. Domain synonyms: клиент, владелец, "
        "хозяин, контакт, клиентская база, client."
    ),
    "get_client_profile": (
        "Build a full client / owner profile in one call: client data, recent "
        "invoices, recent admissions, and the next scheduled visit. Use when the "
        "user asks for a full owner card or consolidated client context. Domain "
        "synonyms: клиент, владелец, хозяин, хозяин питомца, контакт, "
        "клиентская база, client."
    ),
    "get_pet_profile": (
        "Build a full pet / patient profile in one call: pet data, recent medical "
        "cards, and vaccination context. Use when the user asks for a full patient "
        "card or consolidated pet history. Domain synonyms: питомец, пациент, "
        "животное, кот, собака, пациент клиники, pet, animal."
    ),
    "get_medical_cards_by_client_id": (
        "List medical cards for all pets that belong to one client / owner. Use "
        "when the user asks for the medical history of all animals of one owner. "
        "Domain synonyms: медкарта, медицинская карта, история болезни, история "
        "лечения, клиническая запись, осмотр, medical card, medical record."
    ),
    "get_vaccinations": (
        "List vaccination records for one pet / patient. Use when the user asks "
        "about vaccinations, revaccination, vaccine history, or the pet's "
        "vaccination card. Domain synonyms: вакцинация, прививка, прививочная "
        "карта, история вакцинаций, vaccination card, vaccine record."
    ),
    "get_average_invoice": (
        "Calculate the average invoice / bill amount for the requested period. Use "
        "when the user asks for average check, average bill, or average revenue per "
        "invoice. Domain synonyms: счёт, счёт-фактура, чек, квитанция, документ "
        "оплаты, invoice, bill."
    ),
    "add_invoice_document": (
        "Add a new invoice line item to an invoice. Use when the user wants to add "
        "a product or service into an existing bill. Domain synonyms: позиция "
        "счёта, строка счёта, товар в счёте, услуга в счёте, позиция, invoice "
        "document, invoice line."
    ),
    "get_good_stock_balance": (
        "Check current stock balance for goods in warehouse context. Use when the "
        "user asks how much is left in stock, current inventory, or remaining "
        "quantity. Domain synonyms: остаток, остаток на складе, количество на "
        "складе, наличие товара, сколько осталось, запас, stock, inventory."
    ),
    "send_message_to_all": (
        "Send an in-app notification campaign to all clinic users. Use when the "
        "user asks for a broadcast, mass notification, global message, or general "
        "in-app mailing. Domain synonyms: уведомление, рассылка, сообщение в "
        "программу, уведомление пользователям, push в программу, messages."
    ),
    "send_message_to_users": (
        "Send an in-app notification campaign to specific users by ID. Use when "
        "the user wants to notify selected employees or a concrete recipient list. "
        "Domain synonyms: уведомление, рассылка, сообщение в программу, "
        "уведомление пользователям, push в программу, messages."
    ),
    "get_message_reports": (
        "List in-app notification delivery reports and campaign statistics. Use "
        "when the user asks for message campaign status, sent/pending counts, or "
        "notification report details. Domain synonyms: уведомление, рассылка, "
        "сообщение в программу, уведомление пользователям, push в программу, "
        "messages."
    ),
    "send_message_to_roles": (
        "Send an in-app notification campaign to all users with selected roles. "
        "Use when the user wants to notify all veterinarians, administrators, or "
        "another staff role group. Domain synonyms: уведомление, рассылка, "
        "сообщение в программу, уведомление пользователям, push в программу, "
        "messages."
    ),
}


def _domain_synonyms(entity_key: str) -> str:
    synonyms = ENTITY_METADATA[entity_key]["synonyms"]
    return ", ".join(str(item) for item in synonyms)


def _build_generic_description(tool_name: str) -> str | None:
    entity_key = TOOL_ENTITY_MAP.get(tool_name)
    if entity_key is None:
        return None

    singular = str(ENTITY_METADATA[entity_key]["singular"])
    plural = str(ENTITY_METADATA[entity_key]["plural"])
    synonyms = _domain_synonyms(entity_key)

    if tool_name.startswith("get_") and tool_name.endswith("_by_id"):
        return (
            f"Fetch one {singular} by ID. Use when the user already knows the exact "
            f"record identifier. Domain synonyms: {synonyms}."
        )
    if tool_name.startswith("get_"):
        return (
            f"List or fetch {plural}. Use when the user asks to search, browse, "
            f"filter, or inspect this domain area. Domain synonyms: {synonyms}."
        )
    if tool_name.startswith("create_"):
        return (
            f"Create a new {singular}. Use when the user asks to register, add, or "
            f"open a new record in this domain area. Domain synonyms: {synonyms}."
        )
    if tool_name.startswith("update_"):
        return (
            f"Update an existing {singular}. Use when the user asks to change, edit, "
            f"or correct a record in this domain area. Domain synonyms: {synonyms}."
        )
    if tool_name.startswith("delete_"):
        return (
            f"Delete an existing {singular}. Use when the user asks to remove or "
            f"delete a record in this domain area. Domain synonyms: {synonyms}."
        )
    if tool_name.startswith("add_"):
        return (
            f"Add a new {singular} to an existing parent record. Domain synonyms: "
            f"{synonyms}."
        )
    return None


def enhance_tool_descriptions(mcp: FastMCP) -> None:
    """Apply domain-synonym-aware descriptions to all registered MCP tools."""
    provider = getattr(mcp, "_local_provider", None)
    components = getattr(provider, "_components", None)
    if not isinstance(components, dict):
        return

    for key, component in components.items():
        if not key.startswith("tool:"):
            continue

        description = SPECIAL_TOOL_DESCRIPTIONS.get(component.name)
        if description is None:
            description = _build_generic_description(component.name)
        if not description:
            continue

        component.description = description
        fn = getattr(component, "fn", None)
        if fn is not None:
            fn.__doc__ = description
