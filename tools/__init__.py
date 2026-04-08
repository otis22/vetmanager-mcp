from fastmcp import FastMCP


def register_all(mcp: FastMCP) -> None:
    """Register all entity tool modules with the MCP server."""
    from tools.client import register as register_client
    from tools.pet import register as register_pet
    from tools.admission import register as register_admission
    from tools.medical_card import register as register_medical_card
    from tools.invoice import register as register_invoice
    from tools.good import register as register_good
    from tools.user import register as register_user
    from tools.reference import register as register_reference
    from tools.finance import register as register_finance
    from tools.warehouse import register as register_warehouse
    from tools.clinical import register as register_clinical
    from tools.operations import register as register_operations
    from tools.schedule import register as register_schedule

    register_client(mcp)
    register_pet(mcp)
    register_admission(mcp)
    register_medical_card(mcp)
    register_invoice(mcp)
    register_good(mcp)
    register_user(mcp)
    register_reference(mcp)
    register_finance(mcp)
    register_warehouse(mcp)
    register_clinical(mcp)
    register_operations(mcp)
    register_schedule(mcp)
