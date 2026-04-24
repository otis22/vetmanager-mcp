"""Explicit token access registry for MCP tools and user-facing presets."""

from __future__ import annotations

from token_scopes import (
    SCOPE_ADMISSIONS_READ,
    SCOPE_ADMISSIONS_WRITE,
    SCOPE_ANALYTICS_READ,
    SCOPE_ANALYTICS_WRITE,
    SCOPE_CLIENTS_READ,
    SCOPE_CLIENTS_WRITE,
    SCOPE_FINANCE_READ,
    SCOPE_FINANCE_WRITE,
    SCOPE_INVENTORY_READ,
    SCOPE_INVENTORY_WRITE,
    SCOPE_MEDICAL_CARDS_READ,
    SCOPE_MEDICAL_CARDS_WRITE,
    SCOPE_MESSAGING_WRITE,
    SCOPE_PETS_READ,
    SCOPE_PETS_WRITE,
    SCOPE_REFERENCE_READ,
    SCOPE_USERS_READ,
    SCOPE_USERS_WRITE,
    SUPPORTED_TOKEN_SCOPES,
)

PRESET_FULL_ACCESS = "full_access"
PRESET_READ_ONLY = "read_only"
PRESET_FRONTDESK = "frontdesk"
PRESET_DOCTOR = "doctor"
PRESET_FINANCE = "finance"
PRESET_INVENTORY = "inventory"
TOKEN_PRESET_CHOICES = (
    PRESET_FULL_ACCESS,
    PRESET_READ_ONLY,
    PRESET_FRONTDESK,
    PRESET_DOCTOR,
    PRESET_FINANCE,
    PRESET_INVENTORY,
)
TOKEN_PRESET_LABELS: dict[str, str] = {
    PRESET_FULL_ACCESS: "Full access",
    PRESET_READ_ONLY: "Read only",
    PRESET_FRONTDESK: "Front desk",
    PRESET_DOCTOR: "Doctor",
    PRESET_FINANCE: "Finance",
    PRESET_INVENTORY: "Inventory",
}

TOKEN_PRESET_SCOPES: dict[str, tuple[str, ...]] = {
    PRESET_FULL_ACCESS: tuple(sorted(SUPPORTED_TOKEN_SCOPES)),
    PRESET_READ_ONLY: tuple(
        sorted(
            (
                SCOPE_ADMISSIONS_READ,
                SCOPE_ANALYTICS_READ,
                SCOPE_CLIENTS_READ,
                SCOPE_FINANCE_READ,
                SCOPE_INVENTORY_READ,
                SCOPE_MEDICAL_CARDS_READ,
                SCOPE_PETS_READ,
                SCOPE_REFERENCE_READ,
                SCOPE_USERS_READ,
            )
        )
    ),
    PRESET_FRONTDESK: tuple(
        sorted(
            (
                SCOPE_ADMISSIONS_READ,
                SCOPE_ADMISSIONS_WRITE,
                SCOPE_ANALYTICS_READ,
                SCOPE_CLIENTS_READ,
                SCOPE_CLIENTS_WRITE,
                SCOPE_FINANCE_READ,
                SCOPE_MESSAGING_WRITE,
                SCOPE_PETS_READ,
                SCOPE_PETS_WRITE,
                SCOPE_REFERENCE_READ,
                SCOPE_USERS_READ,
            )
        )
    ),
    PRESET_DOCTOR: tuple(
        sorted(
            (
                SCOPE_ADMISSIONS_READ,
                SCOPE_ANALYTICS_READ,
                SCOPE_MEDICAL_CARDS_READ,
                SCOPE_MEDICAL_CARDS_WRITE,
                SCOPE_PETS_READ,
                SCOPE_REFERENCE_READ,
                SCOPE_USERS_READ,
            )
        )
    ),
    PRESET_FINANCE: tuple(
        sorted(
            (
                SCOPE_CLIENTS_READ,
                SCOPE_FINANCE_READ,
                SCOPE_FINANCE_WRITE,
                SCOPE_REFERENCE_READ,
            )
        )
    ),
    PRESET_INVENTORY: tuple(
        sorted(
            (
                SCOPE_INVENTORY_READ,
                SCOPE_INVENTORY_WRITE,
                SCOPE_REFERENCE_READ,
            )
        )
    ),
}

TOOL_REQUIRED_SCOPES: dict[str, tuple[str, ...]] = {
    "add_invoice_document": (SCOPE_FINANCE_WRITE,),
    "create_admission": (SCOPE_ADMISSIONS_WRITE,),
    "create_client": (SCOPE_CLIENTS_WRITE,),
    "create_good": (SCOPE_INVENTORY_WRITE,),
    "create_hospitalization": (SCOPE_MEDICAL_CARDS_WRITE,),
    "create_invoice": (SCOPE_FINANCE_WRITE,),
    "create_medical_card": (SCOPE_MEDICAL_CARDS_WRITE,),
    "create_pet": (SCOPE_PETS_WRITE,),
    "create_supplier": (SCOPE_INVENTORY_WRITE,),
    "create_timesheet": (SCOPE_ANALYTICS_WRITE,),
    "delete_client": (SCOPE_CLIENTS_WRITE,),
    "delete_invoice": (SCOPE_FINANCE_WRITE,),
    "delete_invoice_document": (SCOPE_FINANCE_WRITE,),
    "delete_pet": (SCOPE_PETS_WRITE,),
    "get_admission_by_id": (SCOPE_ADMISSIONS_READ,),
    "get_admissions": (SCOPE_ADMISSIONS_READ,),
    "get_anonymous_clients": (SCOPE_USERS_READ,),
    "get_average_invoice": (SCOPE_FINANCE_READ,),
    "get_breed_by_id": (SCOPE_REFERENCE_READ,),
    "get_breeds": (SCOPE_REFERENCE_READ,),
    "get_cassa_by_id": (SCOPE_FINANCE_READ,),
    "get_cassa_close_by_id": (SCOPE_FINANCE_READ,),
    "get_cassa_closes": (SCOPE_FINANCE_READ,),
    "get_cassas": (SCOPE_FINANCE_READ,),
    "get_cities": (SCOPE_REFERENCE_READ,),
    "get_city_by_id": (SCOPE_REFERENCE_READ,),
    "get_city_types": (SCOPE_REFERENCE_READ,),
    "get_client_by_id": (SCOPE_CLIENTS_READ,),
    "get_client_profile": (
        SCOPE_ADMISSIONS_READ,
        SCOPE_CLIENTS_READ,
        SCOPE_FINANCE_READ,
    ),
    "get_client_upcoming_visits": (SCOPE_ADMISSIONS_READ,),
    "get_clients": (SCOPE_CLIENTS_READ,),
    "get_clinic_by_id": (SCOPE_REFERENCE_READ,),
    "get_clinics": (SCOPE_REFERENCE_READ,),
    "get_closing_of_invoice_by_id": (SCOPE_FINANCE_READ,),
    "get_closing_of_invoices": (SCOPE_FINANCE_READ,),
    "get_combo_manual_item_by_id": (SCOPE_REFERENCE_READ,),
    "get_combo_manual_items": (SCOPE_REFERENCE_READ,),
    "get_combo_manual_name_by_id": (SCOPE_REFERENCE_READ,),
    "get_combo_manual_names": (SCOPE_REFERENCE_READ,),
    "get_daily_schedule": (SCOPE_ADMISSIONS_READ,),
    "get_debtors": (SCOPE_CLIENTS_READ,),
    "get_diagnoses": (SCOPE_MEDICAL_CARDS_READ,),
    "get_doctor_free_slots": (SCOPE_ADMISSIONS_READ, SCOPE_ANALYTICS_READ),
    "get_good_by_id": (SCOPE_INVENTORY_READ,),
    "get_good_group_by_id": (SCOPE_INVENTORY_READ,),
    "get_good_groups": (SCOPE_INVENTORY_READ,),
    "get_good_sale_param_by_id": (SCOPE_INVENTORY_READ,),
    "get_good_sale_params": (SCOPE_INVENTORY_READ,),
    "get_good_stock_balance": (SCOPE_INVENTORY_READ,),
    "get_goods": (SCOPE_INVENTORY_READ,),
    "get_hospital_block_by_id": (SCOPE_MEDICAL_CARDS_READ,),
    "get_hospital_blocks": (SCOPE_MEDICAL_CARDS_READ,),
    "get_hospitalization_by_id": (SCOPE_MEDICAL_CARDS_READ,),
    "get_hospitalizations": (SCOPE_MEDICAL_CARDS_READ,),
    "get_inactive_clients": (SCOPE_CLIENTS_READ,),
    "get_inactive_pets": (
        SCOPE_CLIENTS_READ,
        SCOPE_FINANCE_READ,
        SCOPE_MEDICAL_CARDS_READ,
        SCOPE_PETS_READ,
    ),
    "get_invoice_by_id": (SCOPE_FINANCE_READ,),
    "get_invoice_document_by_id": (SCOPE_FINANCE_READ,),
    "get_invoice_documents": (SCOPE_FINANCE_READ,),
    "get_invoices": (SCOPE_FINANCE_READ,),
    "get_medical_card_by_id": (SCOPE_MEDICAL_CARDS_READ,),
    "get_medical_cards": (SCOPE_MEDICAL_CARDS_READ,),
    "get_medical_cards_by_client_id": (SCOPE_MEDICAL_CARDS_READ, SCOPE_PETS_READ),
    "get_message_reports": (SCOPE_ANALYTICS_READ,),
    "get_party_account_by_id": (SCOPE_INVENTORY_READ,),
    "get_party_account_doc_by_id": (SCOPE_INVENTORY_READ,),
    "get_party_account_docs": (SCOPE_INVENTORY_READ,),
    "get_party_accounts": (SCOPE_INVENTORY_READ,),
    "get_payment_by_id": (SCOPE_FINANCE_READ,),
    "get_payments": (SCOPE_FINANCE_READ,),
    "get_revenue_summary": (SCOPE_FINANCE_READ,),
    "get_pet_by_id": (SCOPE_PETS_READ,),
    "get_pet_profile": (SCOPE_MEDICAL_CARDS_READ, SCOPE_PETS_READ),
    "get_pet_type_by_id": (SCOPE_REFERENCE_READ,),
    "get_pet_types": (SCOPE_REFERENCE_READ,),
    "get_pets": (SCOPE_PETS_READ,),
    "get_properties": (SCOPE_REFERENCE_READ,),
    "get_role_by_id": (SCOPE_REFERENCE_READ,),
    "get_roles": (SCOPE_REFERENCE_READ,),
    "get_store_document_by_id": (SCOPE_INVENTORY_READ,),
    "get_store_documents": (SCOPE_INVENTORY_READ,),
    "get_street_by_id": (SCOPE_REFERENCE_READ,),
    "get_streets": (SCOPE_REFERENCE_READ,),
    "get_supplier_by_id": (SCOPE_INVENTORY_READ,),
    "get_suppliers": (SCOPE_INVENTORY_READ,),
    "get_timesheet_by_id": (SCOPE_ANALYTICS_READ,),
    "get_timesheets": (SCOPE_ANALYTICS_READ,),
    "get_unit_by_id": (SCOPE_REFERENCE_READ,),
    "get_units": (SCOPE_REFERENCE_READ,),
    "get_user_by_id": (SCOPE_USERS_READ,),
    "get_user_position_by_id": (SCOPE_REFERENCE_READ,),
    "get_user_positions": (SCOPE_REFERENCE_READ,),
    "get_users": (SCOPE_USERS_READ,),
    "get_vaccinations": (SCOPE_MEDICAL_CARDS_READ,),
    "send_message_to_all": (SCOPE_MESSAGING_WRITE,),
    "send_message_to_roles": (SCOPE_MESSAGING_WRITE,),
    "send_message_to_users": (SCOPE_MESSAGING_WRITE,),
    "update_admission": (SCOPE_ADMISSIONS_WRITE,),
    "update_client": (SCOPE_CLIENTS_WRITE,),
    "update_good": (SCOPE_INVENTORY_WRITE,),
    "update_hospitalization": (SCOPE_MEDICAL_CARDS_WRITE,),
    "update_invoice": (SCOPE_FINANCE_WRITE,),
    "update_medical_card": (SCOPE_MEDICAL_CARDS_WRITE,),
    "update_pet": (SCOPE_PETS_WRITE,),
    "update_supplier": (SCOPE_INVENTORY_WRITE,),
    "update_user": (SCOPE_USERS_WRITE,),
}

# User-facing advertised preset coverage. Keep explicit: tests import this
# source constant to avoid maintaining a separate mirror fixture.
MARKETED_PRESET_TOOLS: dict[str, tuple[str, ...]] = {
    PRESET_READ_ONLY: (
        "get_admission_by_id",
        "get_admissions",
        "get_anonymous_clients",
        "get_average_invoice",
        "get_breed_by_id",
        "get_breeds",
        "get_cassa_by_id",
        "get_cassa_close_by_id",
        "get_cassa_closes",
        "get_cassas",
        "get_cities",
        "get_city_by_id",
        "get_city_types",
        "get_client_by_id",
        "get_client_profile",
        "get_client_upcoming_visits",
        "get_clients",
        "get_clinic_by_id",
        "get_clinics",
        "get_closing_of_invoice_by_id",
        "get_closing_of_invoices",
        "get_combo_manual_item_by_id",
        "get_combo_manual_items",
        "get_combo_manual_name_by_id",
        "get_combo_manual_names",
        "get_daily_schedule",
        "get_debtors",
        "get_diagnoses",
        "get_doctor_free_slots",
        "get_good_by_id",
        "get_good_group_by_id",
        "get_good_groups",
        "get_good_sale_param_by_id",
        "get_good_sale_params",
        "get_good_stock_balance",
        "get_goods",
        "get_hospital_block_by_id",
        "get_hospital_blocks",
        "get_hospitalization_by_id",
        "get_hospitalizations",
        "get_inactive_clients",
        "get_inactive_pets",
        "get_invoice_by_id",
        "get_invoice_document_by_id",
        "get_invoice_documents",
        "get_invoices",
        "get_medical_card_by_id",
        "get_medical_cards",
        "get_medical_cards_by_client_id",
        "get_message_reports",
        "get_party_account_by_id",
        "get_party_account_doc_by_id",
        "get_party_account_docs",
        "get_party_accounts",
        "get_payment_by_id",
        "get_payments",
        "get_revenue_summary",
        "get_pet_by_id",
        "get_pet_profile",
        "get_pet_type_by_id",
        "get_pet_types",
        "get_pets",
        "get_properties",
        "get_role_by_id",
        "get_roles",
        "get_store_document_by_id",
        "get_store_documents",
        "get_street_by_id",
        "get_streets",
        "get_supplier_by_id",
        "get_suppliers",
        "get_timesheet_by_id",
        "get_timesheets",
        "get_unit_by_id",
        "get_units",
        "get_user_by_id",
        "get_user_position_by_id",
        "get_user_positions",
        "get_users",
        "get_vaccinations",
    ),
    PRESET_FRONTDESK: (
        "create_admission",
        "create_client",
        "create_pet",
        "get_admissions",
        "get_client_by_id",
        "get_client_upcoming_visits",
        "get_clients",
        "get_daily_schedule",
        "get_doctor_free_slots",
        "get_message_reports",
        "get_pet_by_id",
        "get_pets",
        "get_timesheet_by_id",
        "get_timesheets",
        "send_message_to_all",
        "send_message_to_roles",
        "send_message_to_users",
        "update_admission",
        "update_client",
        "update_pet",
    ),
    PRESET_DOCTOR: (
        "create_medical_card",
        "get_admissions",
        "get_daily_schedule",
        "get_diagnoses",
        "get_doctor_free_slots",
        "get_medical_card_by_id",
        "get_medical_cards",
        "get_pet_by_id",
        "get_pet_profile",
        "get_pets",
        "get_timesheet_by_id",
        "get_timesheets",
        "get_user_by_id",
        "get_users",
        "get_vaccinations",
        "update_medical_card",
    ),
    PRESET_FINANCE: (
        "create_invoice",
        "get_average_invoice",
        "get_client_by_id",
        "get_clients",
        "get_closing_of_invoice_by_id",
        "get_closing_of_invoices",
        "get_debtors",
        "get_invoice_by_id",
        "get_invoice_document_by_id",
        "get_invoice_documents",
        "get_invoices",
        "get_payment_by_id",
        "get_payments",
        "get_revenue_summary",
        "update_invoice",
    ),
    PRESET_INVENTORY: (
        "create_good",
        "create_supplier",
        "get_good_by_id",
        "get_good_group_by_id",
        "get_good_groups",
        "get_good_sale_param_by_id",
        "get_good_sale_params",
        "get_good_stock_balance",
        "get_goods",
        "get_party_account_by_id",
        "get_party_account_doc_by_id",
        "get_party_account_docs",
        "get_party_accounts",
        "get_store_document_by_id",
        "get_store_documents",
        "get_supplier_by_id",
        "get_suppliers",
        "update_good",
        "update_supplier",
    ),
}


def normalize_token_preset(preset: str | None) -> str:
    """Return validated token preset, defaulting to full access."""
    value = (preset or PRESET_FULL_ACCESS).strip()
    if value not in TOKEN_PRESET_CHOICES:
        raise ValueError("Unknown token access preset.")
    return value


def get_token_preset_scopes(preset: str | None) -> tuple[str, ...]:
    """Return stable scope bundle for a validated token preset."""
    normalized = normalize_token_preset(preset)
    return TOKEN_PRESET_SCOPES[normalized]


def get_token_preset_label(preset: str | None) -> str:
    """Return user-facing label for a validated token preset."""
    normalized = normalize_token_preset(preset)
    return TOKEN_PRESET_LABELS[normalized]


def get_presets_allowing_tool(tool_name: str) -> tuple[str, ...]:
    """Return user-facing preset labels that advertise access to a tool."""
    labels: list[str] = []
    required_scopes = TOOL_REQUIRED_SCOPES.get(tool_name)
    if required_scopes and set(required_scopes).issubset(TOKEN_PRESET_SCOPES[PRESET_FULL_ACCESS]):
        labels.append(TOKEN_PRESET_LABELS[PRESET_FULL_ACCESS])
    labels.extend(
        TOKEN_PRESET_LABELS[preset]
        for preset, tools in MARKETED_PRESET_TOOLS.items()
        if tool_name in tools and preset != PRESET_FULL_ACCESS
    )
    return tuple(dict.fromkeys(labels))


def infer_token_preset(scopes: tuple[str, ...] | list[str]) -> str | None:
    """Infer preset from an exact scope bundle match."""
    normalized = tuple(sorted(scopes))
    for preset, preset_scopes in TOKEN_PRESET_SCOPES.items():
        if normalized == preset_scopes:
            return preset
    return None
