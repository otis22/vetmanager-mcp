"""MCP Prompts for Vetmanager — ready-made templates for typical clinic workflows."""

from fastmcp import FastMCP
from fastmcp.prompts import Message


def _bearer_runtime_prefix() -> str:
    return (
        "Credentials are already available from the MCP Bearer token. "
        "Do not ask for a clinic domain or API key and do not pass them as tool arguments. "
    )


def register_prompts(mcp: FastMCP) -> None:

    @mcp.prompt
    def daily_schedule(date: str, doctor_id: int = 0) -> list[Message]:
        """Show the admission schedule for a given day.

        Args:
            date: Date in YYYY-MM-DD format.
            doctor_id: Vet doctor ID to focus on (0 = all doctors).
        """
        doctor_note = (
            f"After fetching admissions, focus on doctor ID {doctor_id}. "
            if doctor_id
            else ""
        )
        return [Message(
            _bearer_runtime_prefix()
            + f"Show the clinic admission schedule for {date}. "
            + "Call get_admissions(date=date, limit=100). "
            + doctor_note
            + "Format the result as a readable timetable grouped by doctor."
        )]

    @mcp.prompt
    def find_client(query: str) -> list[Message]:
        """Find a client by name, phone number or partial match.

        Args:
            query: Search query for the client.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Find the clinic client matching '{query}'. "
            + "Call get_clients(name=query, limit=20). "
            + "Display full name, phone, email and client ID."
        )]

    @mcp.prompt
    def client_balance(client_id: int) -> list[Message]:
        """Show the financial balance for a client.

        Args:
            client_id: ID of the client.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Show the financial summary for client ID {client_id}. "
            + "1. Call get_invoices(client_id=client_id, limit=100, sort=[{'property':'create_date','direction':'DESC'}]). "
            + "2. Call get_payments(client_id=client_id, limit=100, sort=[{'property':'id','direction':'DESC'}]). "
            + "Summarise total debt, recent invoices, and the latest payment amount/date."
        )]

    @mcp.prompt
    def book_appointment(
        client_name: str,
        pet_name: str,
        doctor_id: int,
        date: str,
    ) -> list[Message]:
        """Book a new admission appointment for a pet.

        Args:
            client_name: Client name to look up.
            pet_name: Pet name or alias.
            doctor_id: ID of the veterinarian.
            date: Appointment date/time in ISO 8601 format.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Book an appointment for client '{client_name}', pet '{pet_name}', "
            + f"doctor ID {doctor_id}, date {date}. "
            + "1. Call get_clients(name=client_name, limit=20). "
            + "2. From the chosen client, call get_pets(owner_id=client_id, limit=100) and find the pet by alias/name. "
            + "3. Call create_admission(pet_id=pet_id, client_id=client_id, doctor_id=doctor_id, date=date). "
            + "Confirm the created admission ID."
        )]

    @mcp.prompt
    def create_invoice_prompt(
        client_id: int,
        pet_id: int,
        service_name: str,
    ) -> list[Message]:
        """Create a new invoice for a client with a service/good line item.

        Args:
            client_id: ID of the client.
            pet_id: ID of the pet.
            service_name: Name of the service or good to add.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Create an invoice for client ID {client_id}, pet ID {pet_id}, "
            + f"with service or good '{service_name}'. "
            + "1. Call get_goods(name=service_name, limit=20) and choose the correct good_id. "
            + "2. Call create_invoice(client_id=client_id, pet_id=pet_id). "
            + "3. Call add_invoice_document(invoice_id=invoice_id, good_id=good_id, quantity=1, price=selected_price). "
            + "Return the invoice ID and the added line item."
        )]

    @mcp.prompt
    def doctor_workload(doctor_id: int, date_from: str, date_to: str) -> list[Message]:
        """Analyse a doctor's workload over a date range.

        Args:
            doctor_id: ID of the veterinarian.
            date_from: Start date in YYYY-MM-DD format.
            date_to: End date in YYYY-MM-DD format.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Analyse the workload for doctor ID {doctor_id} from {date_from} to {date_to}. "
            + "Fetch admissions for the date range using get_admissions and pagination as needed. "
            + "Filter the returned records by doctor ID and count visits by day. "
            + "Return totals and the busiest days."
        )]

    @mcp.prompt
    def unconfirmed_appointments(date: str) -> list[Message]:
        """List unconfirmed admissions for the next two days.

        Args:
            date: Start date in YYYY-MM-DD format.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"List unconfirmed appointments starting from {date} for the next 2 days. "
            + f"1. Compute end_date = {date} plus 2 days in YYYY-MM-DD format. "
            + f"2. Call get_admissions(date_from='{date}', date_to=end_date, status='not_confirmed', limit=100). "
            + "Show client name, pet name, time, and doctor."
        )]

    @mcp.prompt
    def pet_history(pet_id: int, limit: int = 10) -> list[Message]:
        """Show the medical history of a pet.

        Args:
            pet_id: ID of the pet.
            limit: Number of most recent records to show.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Show the medical history for pet ID {pet_id}, last {limit} records. "
            + "Call get_medical_cards(pet_id=pet_id, limit=limit, "
            + "sort=[{'property':'id','direction':'DESC'}]). "
            + "Format each record with date, doctor, description, diagnosis, and treatment."
        )]

    @mcp.prompt
    def last_vaccinations(pet_id: int) -> list[Message]:
        """Show vaccination history and status for a pet.

        Args:
            pet_id: ID of the pet.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Show vaccination history for pet ID {pet_id}. "
            + "Call get_vaccinations(pet_id=pet_id). "
            + "List vaccine name, date administered, and next due date."
        )]

    @mcp.prompt
    def add_medical_note(
        pet_id: int,
        doctor_id: int,
        note: str,
        diagnosis: str = "",
    ) -> list[Message]:
        """Add a new medical record note to a pet's card.

        Args:
            pet_id: ID of the pet.
            doctor_id: ID of the veterinarian writing the note.
            note: Clinical description or observation text.
            diagnosis: Diagnosis text.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Add a medical note for pet ID {pet_id} by doctor ID {doctor_id}. "
            + f"Description: '{note}'. Diagnosis: '{diagnosis}'. "
            + "Call create_medical_card(patient_id=pet_id, doctor_id=doctor_id, "
            + "date_create=today, description=note, diagnosis=diagnosis). "
            + "Confirm the created medical card ID."
        )]

    @mcp.prompt
    def current_inpatients() -> list[Message]:
        """List all currently hospitalised patients in the clinic."""
        return [Message(
            _bearer_runtime_prefix()
            + "List all current inpatients. "
            + "Call get_hospitalizations(limit=100). "
            + "Keep records where discharge/dateOut is empty or the patient is still admitted. "
            + "Show pet name, owner, doctor, ward/block, and admission date."
        )]

    @mcp.prompt
    def pet_invoices(pet_id: int) -> list[Message]:
        """Show recent invoices associated with a pet.

        Args:
            pet_id: ID of the pet.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Build the invoice history for pet ID {pet_id}. "
            + "1. Call get_pet_by_id(pet_id) to determine the owning client_id. "
            + "2. Call get_invoices(client_id=client_id, limit=100, "
            + "sort=[{'property':'create_date','direction':'DESC'}]). "
            + "3. Keep only invoices related to the target pet when the response includes pet linkage. "
            + "4. For each invoice, call get_invoice_documents(invoice_id=invoice_id, limit=100). "
            + "Show date, total amount, payment status, and line items."
        )]

    @mcp.prompt
    def pet_full_profile(pet_id: int) -> list[Message]:
        """Get the complete profile of a pet.

        Args:
            pet_id: ID of the pet.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Build a full profile for pet ID {pet_id}. "
            + "Prefer get_pet_profile(pet_id) as the primary aggregated tool. "
            + "If more client context is needed, call get_client_by_id using the owner from the pet record. "
            + "Summarise pet details, vaccination status, recent medical history, and recent invoices."
        )]

    @mcp.prompt
    def daily_revenue(date: str) -> list[Message]:
        """Show clinic revenue for a specific day.

        Args:
            date: Date in YYYY-MM-DD format.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Calculate the clinic revenue for {date}. "
            + "Call get_invoices(date_from=date, date_to=date, limit=100) and "
            + "get_payments(limit=100, sort=[{'property':'id','direction':'DESC'}]) if needed. "
            + "Summarise total invoiced, total received, and any doctor breakdown available in the data."
        )]

    @mcp.prompt
    def unpaid_invoices(limit: int = 50) -> list[Message]:
        """List all unpaid or partially paid invoices.

        Args:
            limit: Max number of invoices to inspect.
        """
        return [Message(
            _bearer_runtime_prefix()
            + "List unpaid or partially paid invoices. "
            + f"1. Call get_invoices(payment_status='none', limit={limit}, sort=[{{'property':'create_date','direction':'DESC'}}]). "
            + f"2. Call get_invoices(payment_status='partial', limit={limit}, sort=[{{'property':'create_date','direction':'DESC'}}]). "
            + "Merge both lists. Show client name, pet name, invoice date, total amount, and amount due."
        )]

    @mcp.prompt
    def popular_services(date_from: str, date_to: str, top_n: int = 10) -> list[Message]:
        """Show top goods/services by count and revenue over a date range.

        Args:
            date_from: Start date in YYYY-MM-DD format.
            date_to: End date in YYYY-MM-DD format.
            top_n: Number of top positions to show.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Show the top {top_n} services and goods from {date_from} to {date_to}. "
            + "Call get_invoices(date_from=date_from, date_to=date_to, limit=100). "
            + "For each invoice, call get_invoice_documents(invoice_id=invoice_id, limit=100). "
            + "Group by good_id, count occurrences, sum revenue, and return a ranked table."
        )]

    @mcp.prompt
    def search_good(query: str) -> list[Message]:
        """Search for a good or service in the clinic catalog.

        Args:
            query: Name or partial name of the good/service.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Search for goods or services matching '{query}'. "
            + "Call get_goods(title=query, limit=20). "
            + "Show good ID, name, group, price, and unit when available."
        )]

    @mcp.prompt
    def low_stock(threshold: int = 5) -> list[Message]:
        """List goods with stock quantity below a threshold.

        Args:
            threshold: Quantity below which stock is considered low.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"Find goods with stock quantity below {threshold}. "
            + "Use get_goods(limit=100) to identify candidate goods and "
            + "get_good_stock_balance(good_id=..., clinic_id=1) to check balances. "
            + "Return only goods whose quantity is below the threshold."
        )]

    @mcp.prompt
    def new_clients(since_date: str) -> list[Message]:
        """List clients registered since a given date.

        Args:
            since_date: Start date in YYYY-MM-DD format.
        """
        return [Message(
            _bearer_runtime_prefix()
            + f"List clients registered since {since_date}. "
            + "Call get_clients(limit=100, sort=[{'property':'id','direction':'DESC'}]) "
            + "and keep records whose registration/create date is on or after the requested date. "
            + "Show client name, phone, email, registration date, and number of pets when available."
        )]

    @mcp.prompt
    def client_no_visit(days_without_visit: int = 365) -> list[Message]:
        """List clients who have not visited the clinic for a specified number of days.

        Args:
            days_without_visit: Number of days without a visit.
        """
        # Ceiling division so that days=365 → 13 months (≥365d window).
        # Floor would give 12 months (~360d) and under-filter the threshold.
        months_min = max(1, (days_without_visit + 29) // 30)
        return [Message(
            _bearer_runtime_prefix()
            + f"Find clients who have not visited in {days_without_visit}+ days. "
            + f"Call get_inactive_clients(months_min={months_min}, months_max=9999, limit=100). "
            + "Show client name, phone, last visit date, and pets."
        )]
