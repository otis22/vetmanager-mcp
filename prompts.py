"""MCP Prompts for Vetmanager — ready-made templates for typical clinic workflows."""

from fastmcp import FastMCP
from fastmcp.prompts import Message


def register_prompts(mcp: FastMCP) -> None:

    # ── Administrator prompts ─────────────────────────────────────────────────

    @mcp.prompt
    def daily_schedule(domain: str, api_key: str, date: str, doctor_id: int = 0) -> list[Message]:
        """Show the admission schedule for a given day, optionally filtered by doctor.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            date: Date in YYYY-MM-DD format.
            doctor_id: Vet doctor ID to filter by (0 = all doctors).
        """
        filter_note = f" for doctor ID {doctor_id}" if doctor_id else " for all doctors"
        return [Message(
            f"Show the clinic admission schedule for {date}{filter_note}. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_admissions with the date parameter. "
            "Format the result as a readable timetable grouped by doctor."
        )]

    @mcp.prompt
    def find_client(domain: str, api_key: str, query: str) -> list[Message]:
        """Find a client by name, phone number or partial match.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            query: Search query — client name or phone number.
        """
        return [Message(
            f"Find the clinic client matching '{query}'. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_clients with the name parameter. "
            "Display full name, phone, email and client ID."
        )]

    @mcp.prompt
    def client_balance(domain: str, api_key: str, client_id: int) -> list[Message]:
        """Show the financial balance for a client — unpaid invoices and recent payments.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            client_id: ID of the client.
        """
        return [Message(
            f"Show the financial summary for client ID {client_id}. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "1. Call get_invoices filtered by client_id to find open invoices. "
            "2. Call get_payments filtered by client_id to find recent payments. "
            "Summarise: total debt, last payment date and amount."
        )]

    @mcp.prompt
    def book_appointment(domain: str, api_key: str, client_name: str, pet_name: str, doctor_id: int, date: str) -> list[Message]:
        """Book a new admission appointment for a pet.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            client_name: Client's name to look up.
            pet_name: Pet's name/alias.
            doctor_id: ID of the veterinarian.
            date: Appointment date/time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
        """
        return [Message(
            f"Book an appointment: client '{client_name}', pet '{pet_name}', "
            f"doctor ID {doctor_id}, date {date}. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Steps: 1) find client by name with get_clients, "
            "2) find pet by client_id with get_pets, "
            "3) call create_admission with pet_id, client_id, doctor_id, date. "
            "Confirm the created admission ID."
        )]

    @mcp.prompt
    def create_invoice_prompt(domain: str, api_key: str, client_id: int, pet_id: int, service_name: str) -> list[Message]:
        """Create a new invoice for a client with a service/good line item.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            client_id: ID of the client.
            pet_id: ID of the pet.
            service_name: Name of the service or good to add.
        """
        return [Message(
            f"Create an invoice for client ID {client_id}, pet ID {pet_id} "
            f"with service/good '{service_name}'. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Steps: 1) find the good by name with get_goods, "
            "2) call create_invoice with client_id and pet_id, "
            "3) call add_invoice_document with invoice_id, good_id, quantity=1, price from catalog. "
            "Return the invoice ID."
        )]

    @mcp.prompt
    def doctor_workload(domain: str, api_key: str, doctor_id: int, date_from: str, date_to: str) -> list[Message]:
        """Analyse a doctor's workload (admissions count) over a date range.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            doctor_id: ID of the veterinarian.
            date_from: Start date in YYYY-MM-DD format.
            date_to: End date in YYYY-MM-DD format.
        """
        return [Message(
            f"Analyse the workload for doctor ID {doctor_id} from {date_from} to {date_to}. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_admissions for each date or page through results filtering by doctor. "
            "Count total admissions and list days with the most visits."
        )]

    @mcp.prompt
    def unconfirmed_appointments(domain: str, api_key: str, date: str) -> list[Message]:
        """List unconfirmed (status != confirmed) admissions for the next 2 days.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            date: Start date in YYYY-MM-DD format (today).
        """
        return [Message(
            f"List unconfirmed appointments starting from {date} for the next 2 days. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_admissions with date filter and check admission status field. "
            "Show client name, pet name, time, and doctor for each unconfirmed record."
        )]

    # ── Vet doctor prompts ────────────────────────────────────────────────────

    @mcp.prompt
    def pet_history(domain: str, api_key: str, pet_id: int, limit: int = 10) -> list[Message]:
        """Show the medical history of a pet (last N records).

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_id: ID of the pet.
            limit: Number of most recent records to show (default 10).
        """
        return [Message(
            f"Show the medical history for pet ID {pet_id}, last {limit} records. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_medical_cards with pet_id and limit. "
            "Format each record with date, doctor, description, diagnosis, treatment."
        )]

    @mcp.prompt
    def last_vaccinations(domain: str, api_key: str, pet_id: int) -> list[Message]:
        """Show vaccination history and status for a pet.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_id: ID of the pet.
        """
        return [Message(
            f"Show vaccination history for pet ID {pet_id}. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_medical_cards with pet_id and search for records containing 'вакцин' or 'vaccination' in description. "
            "List vaccine name, date administered, and next due date if mentioned."
        )]

    @mcp.prompt
    def add_medical_note(domain: str, api_key: str, pet_id: int, doctor_id: int, note: str, diagnosis: str = "") -> list[Message]:
        """Add a new medical record note to a pet's card.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_id: ID of the pet.
            doctor_id: ID of the veterinarian writing the note.
            note: Clinical description or observation text.
            diagnosis: Diagnosis text (optional).
        """
        today = "today"
        return [Message(
            f"Add a medical note for pet ID {pet_id} by doctor ID {doctor_id}. "
            f"Note: '{note}'. Diagnosis: '{diagnosis}'. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            f"Call create_medical_card with pet_id={pet_id}, doctor_id={doctor_id}, "
            f"date={today}, description=note, diagnosis=diagnosis. "
            "Confirm the created record ID."
        )]

    @mcp.prompt
    def current_inpatients(domain: str, api_key: str) -> list[Message]:
        """List all currently hospitalised patients in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
        """
        return [Message(
            "List all current inpatients (hospitalizations without discharge date). "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_hospitalizations. Filter or note records where dateOut is empty. "
            "Show pet name, owner, admitting doctor, ward/block, and admission date."
        )]

    @mcp.prompt
    def pet_invoices(domain: str, api_key: str, pet_id: int) -> list[Message]:
        """Show all invoices associated with a pet.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_id: ID of the pet.
        """
        return [Message(
            f"Show all invoices for pet ID {pet_id}. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_invoices filtered by pet_id. "
            "For each invoice show: date, total amount, payment status, and line items (call get_invoice_documents)."
        )]

    @mcp.prompt
    def pet_full_profile(domain: str, api_key: str, pet_id: int) -> list[Message]:
        """Get the complete profile of a pet: owner balance, last visit, vaccinations, recent records, recent invoices.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_id: ID of the pet.
        """
        return [Message(
            f"Build a full profile for pet ID {pet_id}. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Gather the following in parallel: "
            "1) pet info via get_pet_by_id, "
            "2) owner info via get_client_by_id using pet's client_id, "
            "3) last 3 medical cards via get_medical_cards, "
            "4) last 3 invoices via get_invoices, "
            "5) last admission date via get_admissions. "
            "Summarise into a structured card: pet details, owner balance, last visit, "
            "vaccination status, recent notes, open invoices."
        )]

    # ── Financial prompts ─────────────────────────────────────────────────────

    @mcp.prompt
    def daily_revenue(domain: str, api_key: str, date: str) -> list[Message]:
        """Show clinic revenue for a specific day, broken down by doctor.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            date: Date in YYYY-MM-DD format.
        """
        return [Message(
            f"Calculate the clinic revenue for {date}. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_invoices filtered by date. Sum amounts per doctor. "
            "Also call get_payments for the same date. "
            "Report: total invoiced, total received, and per-doctor breakdown."
        )]

    @mcp.prompt
    def unpaid_invoices(domain: str, api_key: str, limit: int = 50) -> list[Message]:
        """List all unpaid or partially paid invoices.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max number of invoices to check (default 50).
        """
        return [Message(
            "List unpaid or partially paid invoices. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            f"Call get_invoices with limit={limit}. "
            "Filter those where payment status indicates unpaid/partial. "
            "Show client name, pet name, invoice date, total amount, and amount due."
        )]

    @mcp.prompt
    def popular_services(domain: str, api_key: str, date_from: str, date_to: str, top_n: int = 10) -> list[Message]:
        """Show top goods/services by count and revenue over a date range.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            date_from: Start date in YYYY-MM-DD format.
            date_to: End date in YYYY-MM-DD format.
            top_n: Number of top positions to show (default 10).
        """
        return [Message(
            f"Show the top {top_n} services and goods by usage from {date_from} to {date_to}. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_invoices to get invoices in the period, then call get_invoice_documents for each. "
            "Group by good_id, count occurrences and sum revenue. "
            "Return a ranked table: position, good name, count, total revenue."
        )]

    # ── Warehouse & client base prompts ───────────────────────────────────────

    @mcp.prompt
    def search_good(domain: str, api_key: str, query: str) -> list[Message]:
        """Search for a good or service in the clinic price list.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            query: Name or partial name of the good/service.
        """
        return [Message(
            f"Search for goods/services matching '{query}' in the price list. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_goods with name=query. "
            "Show: good ID, name, group, price, unit."
        )]

    @mcp.prompt
    def low_stock(domain: str, api_key: str, threshold: int = 5) -> list[Message]:
        """List goods with stock quantity below a threshold.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            threshold: Quantity below which stock is considered low (default 5).
        """
        return [Message(
            f"Find goods with stock quantity below {threshold}. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_good_sale_params to get current stock levels. "
            "Filter items where quantity < threshold. "
            "Show: good name, current quantity, unit, supplier if available."
        )]

    @mcp.prompt
    def new_clients(domain: str, api_key: str, since_date: str) -> list[Message]:
        """List clients registered since a given date.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            since_date: Start date in YYYY-MM-DD format.
        """
        return [Message(
            f"List clients registered since {since_date}. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_clients with date filter or sort by registration date. "
            "Show: client name, phone, email, registration date, number of pets."
        )]

    @mcp.prompt
    def client_no_visit(domain: str, api_key: str, days_without_visit: int = 365) -> list[Message]:
        """List clients who have not visited the clinic for a specified number of days.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            days_without_visit: Number of days without a visit (default 365).
        """
        return [Message(
            f"Find clients who haven't visited in {days_without_visit}+ days. "
            f"Use domain='{domain}' and api_key='{api_key}'. "
            "Call get_admissions sorted by date descending. "
            "For each client find their last admission date. "
            "Return clients whose last visit was more than {days_without_visit} days ago. "
            "Show: client name, phone, last visit date, pets."
        )]
