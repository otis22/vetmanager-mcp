from fastmcp import FastMCP

from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_clients(
        domain: str,
        api_key: str,
        limit: int = 20,
        offset: int = 0,
        name: str = "",
    ) -> dict:
        """List clients of the clinic.

        Args:
            domain: Clinic subdomain (e.g. 'myclinic').
            api_key: REST API key from Vetmanager Settings → Integration → Rest API.
            limit: Max number of records to return (default 20).
            offset: Pagination offset.
            name: Filter by client name (partial match).
        """
        client = VetmanagerClient(domain, api_key)
        params: dict = {"limit": limit, "offset": offset}
        if name:
            params["name"] = name
        return await client.get("/rest/api/client", params=params)

    @mcp.tool
    async def get_client_by_id(
        domain: str,
        api_key: str,
        client_id: int,
    ) -> dict:
        """Get a clinic client by their unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            client_id: Unique numeric ID of the client.
        """
        client = VetmanagerClient(domain, api_key)
        return await client.get(f"/rest/api/client/{client_id}")

    @mcp.tool
    async def create_client(
        domain: str,
        api_key: str,
        first_name: str,
        last_name: str,
        phone: str = "",
        email: str = "",
    ) -> dict:
        """Create a new client in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            first_name: Client's first name.
            last_name: Client's last name.
            phone: Contact phone number.
            email: Contact email address.
        """
        client = VetmanagerClient(domain, api_key)
        payload: dict = {"firstName": first_name, "lastName": last_name}
        if phone:
            payload["phone"] = phone
        if email:
            payload["email"] = email
        return await client.post("/rest/api/client", json=payload)

    @mcp.tool
    async def update_client(
        domain: str,
        api_key: str,
        client_id: int,
        first_name: str = "",
        last_name: str = "",
        phone: str = "",
        email: str = "",
    ) -> dict:
        """Update an existing client's information.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            client_id: ID of the client to update.
            first_name: New first name (leave empty to keep current).
            last_name: New last name (leave empty to keep current).
            phone: New phone number.
            email: New email address.
        """
        client = VetmanagerClient(domain, api_key)
        payload: dict = {}
        if first_name:
            payload["firstName"] = first_name
        if last_name:
            payload["lastName"] = last_name
        if phone:
            payload["phone"] = phone
        if email:
            payload["email"] = email
        return await client.put(f"/rest/api/client/{client_id}", json=payload)
