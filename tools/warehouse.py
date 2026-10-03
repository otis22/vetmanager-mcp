"""Warehouse/inventory entity tools: GoodGroup, GoodSaleParam, PartyAccount,
PartyAccountDoc, StoreDocument, Suppliers."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import hmac
import json
import time

from fastmcp import FastMCP
from exceptions import ToolInputError, reportable_error
from filters import FILTER_FIELDS_BY_ENTITY, eq as _filter_eq, in_ as _filter_in
from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update
from validators import LimitParam
from vetmanager_client import VetmanagerClient
from runtime_auth import get_current_runtime_credentials

# Этап 298. Сколько строк цены один вызов вправе переписать. Больше — работа
# для отчёта и рук клиники, а не для одного вызова агента: цену видят клиенты,
# и откатывать массовую ошибку придётся тоже руками.
_PRICE_UPDATE_ROW_LIMIT = 50
# Сколько строк инструмент вообще согласен прочитать, прежде чем сказать, что
# такая переоценка делается не одним вызовом.
_PRICE_UPDATE_FETCH_LIMIT = 500
_PRICE_SCOPES = ("row", "good", "group")
_MONEY = Decimal("0.01")
_SALE_STATUSES = frozenset({"active", "disabled"})
_STATUS_PREVIEW_TTL = 600
_STATUS_SNAPSHOT_FIELDS = (
    "id", "good_id", "clinic_id", "unit_sale_id", "status", "price",
    "coefficient", "min_price", "max_price", "markup", "price_formation",
    "is_partial_sale", "is_skip_marking", "barcode",
)


def _status_snapshot(row: dict) -> dict:
    return {field: row.get(field) for field in _STATUS_SNAPSHOT_FIELDS}


def _status_signature(snapshot: dict, target_status: str, issued: int) -> str:
    credentials = get_current_runtime_credentials()
    if credentials is None or not credentials.vetmanager_auth.credential:
        raise ToolInputError("No active connection for sale status preview.")
    auth = credentials.vetmanager_auth
    key = hmac.new(auth.credential.encode(), b"good-sale-status-preview-v1", hashlib.sha256).digest()
    message = json.dumps({
        "snapshot": snapshot, "target": target_status, "issued": issued,
        "account_id": credentials.account_id, "connection_id": credentials.connection_id,
        "domain": auth.domain, "auth_mode": auth.auth_mode,
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_good_groups(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List product/service groups in the clinic catalog.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/GoodGroup", limit=limit, offset=offset, sort=sort, filters=filter,
            allowed_filter_properties=FILTER_FIELDS_BY_ENTITY["goodGroup"],
        )

    @mcp.tool
    async def get_good_group_by_id(group_id: int) -> dict:
        """Get a product/service group by its unique ID.

        Args:
            group_id: Unique numeric ID of the group.
        """
        return await crud_get_by_id("/rest/api/GoodGroup", group_id)

    @mcp.tool
    async def get_good_sale_params(
        good_id: int,
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List sale parameters (pricing, units) for a specific good/service.

        Args:
            good_id: ID of the good/service.
            limit: Max records to return.
            offset: Pagination offset.
            filter/sort: Optional raw clauses. Allowed properties for both: barcode, clinic_id,
                coefficient, good_id, id, is_partial_sale, is_skip_marking,
                markup, max_price, min_price, price, price_formation, status,
                unit_sale_id.
        """
        combined_filters: list = list(filter or [])
        if good_id:
            combined_filters.append(_filter_eq("good_id", good_id))
        return await crud_list(
            "/rest/api/goodSaleParam", limit=limit, offset=offset,
            sort=sort, filters=combined_filters if combined_filters else None,
            allowed_filter_properties=FILTER_FIELDS_BY_ENTITY["goodSaleParam"],
        )

    @mcp.tool
    async def get_good_sale_param_by_id(param_id: int) -> dict:
        """Get a good sale parameter record by its unique ID.

        Args:
            param_id: Unique numeric ID of the sale parameter.
        """
        return await crud_get_by_id("/rest/api/goodSaleParam", param_id)

    @mcp.tool
    async def get_party_accounts(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List inventory batch (party) accounts.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/PartyAccount", limit=limit, offset=offset, sort=sort, filters=filter,
            allowed_filter_properties=FILTER_FIELDS_BY_ENTITY["partyAccount"],
        )

    @mcp.tool
    async def get_party_account_by_id(party_id: int) -> dict:
        """Get an inventory batch account by its unique ID.

        Args:
            party_id: Unique numeric ID of the party account.
        """
        return await crud_get_by_id("/rest/api/PartyAccount", party_id)

    @mcp.tool
    async def get_party_account_docs(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List documents associated with inventory batch accounts.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/PartyAccountDoc", limit=limit, offset=offset, sort=sort, filters=filter,
            allowed_filter_properties=FILTER_FIELDS_BY_ENTITY["partyAccountDoc"],
        )

    @mcp.tool
    async def get_party_account_doc_by_id(doc_id: int) -> dict:
        """Get a batch account document by its unique ID.

        Args:
            doc_id: Unique numeric ID of the document.
        """
        return await crud_get_by_id("/rest/api/PartyAccountDoc", doc_id)

    @mcp.tool
    async def get_store_documents(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List warehouse/store documents (receipts, write-offs, transfers).

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/StoreDocument", limit=limit, offset=offset, sort=sort, filters=filter,
            allowed_filter_properties=FILTER_FIELDS_BY_ENTITY["storeDocument"],
        )

    @mcp.tool
    async def get_store_document_by_id(doc_id: int) -> dict:
        """Get a store document by its unique ID.

        Args:
            doc_id: Unique numeric ID of the store document.
        """
        return await crud_get_by_id("/rest/api/StoreDocument", doc_id)

    @mcp.tool
    async def get_suppliers(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List suppliers/counterparties in the clinic system.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/Suppliers", limit=limit, offset=offset, sort=sort, filters=filter,
            allowed_filter_properties=FILTER_FIELDS_BY_ENTITY["suppliers"],
        )

    @mcp.tool
    async def get_supplier_by_id(supplier_id: int) -> dict:
        """Get a supplier by its unique ID.

        Args:
            supplier_id: Unique numeric ID of the supplier.
        """
        return await crud_get_by_id("/rest/api/Suppliers", supplier_id)

    @mcp.tool
    async def create_supplier(
        company_name: str,
        contact_person: str = "",
        phone: str = "",
        mail: str = "",
        address: str = "",
        note: str = "",
    ) -> dict:
        """Create a new supplier/counterparty in the clinic system.

        Args:
            company_name: Company or individual name (required).
            contact_person: Contact person name.
            phone: Contact phone number.
            mail: Email address.
            address: Postal address.
            note: Additional notes.
        """
        payload: dict = {"company_name": company_name}
        if contact_person:
            payload["contact_person"] = contact_person
        if phone:
            payload["phone"] = phone
        if mail:
            payload["mail"] = mail
        if address:
            payload["address"] = address
        if note:
            payload["note"] = note
        return await crud_create("/rest/api/Suppliers", payload)

    def _price_row(payload: dict) -> dict:
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        row = data.get("goodSaleParam") if isinstance(data, dict) else None
        if not isinstance(row, dict) or not row.get("id"):
            raise reportable_error("Vetmanager returned no sale parameter record.")
        return row

    @mcp.tool
    async def set_good_sale_param_status(
        sale_param_id: int,
        clinic_id: int,
        target_status: str,
        confirm: bool = False,
        confirmation: str = "",
    ) -> dict:
        """Preview or change one sale option in invoice selection.

        Call first without confirm to see the good, clinic, sale unit and current
        status. Then call separately with confirm=true and the returned
        confirmation. Disabling this row makes this particular good/clinic/unit
        combination inactive for new invoice selection; other clinics and units
        are untouched. To restore it, preview target_status='active'.

        Args:
            sale_param_id: Exact goodSaleParam row ID, not good ID.
            clinic_id: Expected clinic of that sale row; must match the row.
            target_status: 'disabled' or 'active'.
            confirm: False previews without writing; True applies the preview.
            confirmation: Opaque token from this row's fresh preview, valid 10 min.
        """
        if sale_param_id <= 0 or clinic_id <= 0:
            raise ToolInputError("sale_param_id and clinic_id must be positive.")
        if target_status not in _SALE_STATUSES:
            raise ToolInputError("target_status must be 'active' or 'disabled'.")
        if bool(confirm) != bool(confirmation):
            raise ToolInputError("Confirmation is required only with confirm=true.")

        row = _price_row(await crud_get_by_id("/rest/api/goodSaleParam", sale_param_id,
                                             fresh=True))
        if int(row.get("id") or 0) != sale_param_id:
            raise reportable_error("Vetmanager returned a different sale parameter.")
        if int(row.get("clinic_id") or 0) != clinic_id:
            raise ToolInputError("Sale parameter belongs to a different clinic.")
        current = row.get("status")
        if current not in _SALE_STATUSES:
            raise ToolInputError("Unknown sale parameter status; no write was sent.")
        good_id = int(row.get("good_id") or 0)
        unit_id = int(row.get("unit_sale_id") or 0)
        if good_id <= 0 or unit_id < 0:
            raise reportable_error("Sale parameter has invalid good or sale unit ID.")
        snapshot = _status_snapshot(row)

        if confirm:
            try:
                issued_text, signature = confirmation.split(".", 1)
                issued = int(issued_text)
                if not issued_text.isdecimal() or len(signature) != 64:
                    raise ValueError
            except (ValueError, AttributeError):
                raise ToolInputError("Invalid confirmation; preview again.") from None
            age = int(time.time()) - issued
            if age < 0 or age > _STATUS_PREVIEW_TTL:
                raise ToolInputError("Confirmation expired or is from the future; preview again.")
            expected = _status_signature(snapshot, target_status, issued)
            if not hmac.compare_digest(signature, expected):
                raise ToolInputError("Sale option changed or confirmation does not match; preview again.")
            if current == target_status:
                return {"applied": False, "sale_param_id": sale_param_id,
                        "clinic_id": clinic_id, "before": current, "after": current}
            try:
                await crud_update("/rest/api/goodSaleParam", sale_param_id,
                                  {"status": target_status})
            except Exception as exc:
                raise reportable_error(
                    "Sale status write outcome is unknown; read the row before retrying."
                ) from exc
            try:
                after = _price_row(await crud_get_by_id("/rest/api/goodSaleParam", sale_param_id,
                                                        fresh=True))
            except Exception as exc:
                raise reportable_error(
                    "Sale status write was sent, but verification failed; read the row."
                ) from exc
            if (_status_snapshot(after) != dict(snapshot, status=target_status)):
                raise reportable_error(
                    "Sale status write was sent, but readback differs; read the row."
                )
            return {"applied": True, "sale_param_id": sale_param_id,
                    "clinic_id": clinic_id, "before": current, "after": after["status"]}

        good_payload = await crud_get_by_id("/rest/api/good", good_id)
        data = good_payload.get("data", {}) if isinstance(good_payload, dict) else {}
        good = data.get("good") if isinstance(data, dict) else None
        if not isinstance(good, dict) or int(good.get("id") or 0) != good_id:
            raise reportable_error("Vetmanager returned no matching good.")
        clinic_payload = await crud_get_by_id("/rest/api/clinics", clinic_id)
        clinic_data = clinic_payload.get("data", {}) if isinstance(clinic_payload, dict) else {}
        clinic = clinic_data.get("clinics") if isinstance(clinic_data, dict) else None
        if not isinstance(clinic, dict) or int(clinic.get("id") or 0) != clinic_id:
            raise reportable_error("Vetmanager returned no matching clinic.")
        last_active = None
        if current == "active" and target_status == "disabled":
            active = await crud_list(
                "/rest/api/goodSaleParam", limit=2, offset=0,
                filters=[_filter_eq("good_id", good_id), _filter_eq("clinic_id", clinic_id),
                         _filter_eq("status", "active")],
                allowed_filter_properties=FILTER_FIELDS_BY_ENTITY["goodSaleParam"],
            )
            active_data = active.get("data", {}) if isinstance(active, dict) else {}
            active_rows = active_data.get("goodSaleParam") if isinstance(active_data, dict) else None
            total = active_data.get("totalCount") if isinstance(active_data, dict) else None
            if isinstance(active_rows, list) and str(total).isdecimal():
                last_active = int(total) == 1 and len(active_rows) == 1 and int(
                    active_rows[0].get("id") or 0) == sale_param_id

        issued = int(time.time())
        signature = _status_signature(snapshot, target_status, issued)
        return {
            "applied": False, "sale_param_id": sale_param_id, "clinic_id": clinic_id,
            "clinic": {"id": clinic_id, "title": clinic.get("title")},
            "good": {"id": good_id, "title": good.get("title")},
            "unit_sale_id": unit_id,
            "unit_sale_title": (row.get("unitSale") or {}).get("title")
                if isinstance(row.get("unitSale"), dict) else None,
            "current_status": current, "target_status": target_status,
            "last_active_sale_option": last_active,
            "effect": "This exact good/clinic/sale-unit combination becomes inactive "
                "for new invoice selection." if target_status == "disabled" else
                "This exact good/clinic/sale-unit combination becomes active "
                "for new invoice selection.",
            "warning": "This may be the last active sale option for the good in this clinic."
                if last_active is True else None,
            "confirmation": f"{issued}.{signature}",
        }

    def _caller_number(value, *, field: str) -> Decimal:
        """Число от вызывающего — отказ, а не падение.

        Внешнее ревью (finding medium): `Decimal(str(float("inf")))` доходит до
        `quantize` и поднимает `InvalidOperation` — это боевой crash, а не
        контролируемый отказ.
        """
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ToolInputError(f"{field} must be a decimal number, got {value!r}")
        if not number.is_finite():
            raise ToolInputError(f"{field} must be a finite number, got {value!r}")
        return number

    def _apply_change(current: Decimal, new_price, change_percent) -> Decimal:
        if new_price:
            target = _caller_number(new_price, field="new_price")
        else:
            percent = _caller_number(change_percent, field="change_percent")
            target = current * (Decimal("1") + percent / Decimal("100"))
        target = target.quantize(_MONEY, rounding=ROUND_HALF_UP)
        if target <= 0:
            raise ToolInputError("Resulting price must be positive.")
        return target

    def _sale_band(price: Decimal, row: dict) -> dict:
        """Коридор скидки и наценки при продаже — не ограничение на цену.

        `min_price` и `max_price` в Ветменеджере — **проценты**, а не рубли:

            $minPrice = $price - $price * $min_price / 100;
            $maxPrice = $price + $price * $max_price / 100;

        (`GoodController.php`; миграция 2014 года
        `m140311_081943_update_good_sets_max_min_to_percents` перевела старые
        абсолютные значения в проценты.) Коридор считается от текущей цены,
        то есть двигается вместе с ней — запретить им установку новой цены
        нельзя, можно только показать последствие.
        """
        min_pct = _money(row.get("min_price") or 0, field="min_price")
        max_pct = _money(row.get("max_price") or 0, field="max_price")
        return {
            "min": str((price - price * min_pct / 100).quantize(_MONEY, rounding=ROUND_HALF_UP)),
            "max": str((price + price * max_pct / 100).quantize(_MONEY, rounding=ROUND_HALF_UP)),
            "min_percent": str(min_pct),
            "max_percent": str(max_pct),
            "note": (
                "min_price и max_price — проценты отклонения от цены, "
                "а не рубли: это допустимая скидка и наценка при продаже, "
                "а не ограничение на саму цену."
            ),
        }

    def _is_writable(row: dict) -> bool:
        """Строка с `increase` берёт цену из наценки — запись туда бесследна."""
        return str(row.get("price_formation") or "") != "increase"

    def _writable_count(rows: list[dict]) -> int:
        return sum(1 for row in rows if _is_writable(row))

    def _money(value, *, field: str) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise reportable_error(f"Sale parameter carries an unusable {field}: {value!r}")

    async def _all_rows(endpoint: str, key: str, filters: list, what: str) -> list[dict]:
        """Все строки, а не первая страница.

        Внешнее ревью 05.09.2026 (finding high): выборка шла одной страницей по
        100 и игнорировала `totalCount`. На большой группе превью было бы
        неполным, а обновление — частичным, причём молча. Для цен молчаливая
        неполнота хуже отказа: половина товаров переоценена, половина нет, и
        никто об этом не знает.
        """
        collected: list[dict] = []
        seen_ids: set[int] = set()
        offset = 0
        expected_total: int | None = None
        page_size = 100
        while True:
            payload = await crud_list(
                endpoint, limit=page_size, offset=offset, filters=filters,
                allowed_filter_properties=FILTER_FIELDS_BY_ENTITY[key],
            )
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            rows = data.get(key) if isinstance(data, dict) else None
            batch = [row for row in rows or [] if isinstance(row, dict)]
            total = data.get("totalCount") if isinstance(data, dict) else None
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise reportable_error(
                    f"{what}: Vetmanager list response has no trustworthy integer "
                    "totalCount; no prices were changed."
                )
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise reportable_error(
                    f"{what}: Vetmanager changed totalCount during pagination; "
                    "no prices were changed."
                )
            if total > _PRICE_UPDATE_FETCH_LIMIT:
                raise ToolInputError(
                    f"{what}: Vetmanager reports {total} records, above the "
                    f"{_PRICE_UPDATE_FETCH_LIMIT} this tool will read. A repricing that "
                    "wide is done from a report and by hand — a partial pass over prices "
                    "is worse than none."
                )
            if len(batch) > page_size:
                raise reportable_error(
                    f"{what}: Vetmanager returned more rows than requested; "
                    "no prices were changed."
                )
            for item in batch:
                item_id = item.get("id")
                if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id <= 0:
                    raise reportable_error(
                        f"{what}: Vetmanager returned a row without a usable id; "
                        "no prices were changed."
                    )
                if item_id in seen_ids:
                    raise reportable_error(
                        f"{what}: Vetmanager repeated a row during pagination; "
                        "no prices were changed."
                    )
                seen_ids.add(item_id)
            collected.extend(batch)
            if len(collected) > total:
                raise reportable_error(
                    f"{what}: Vetmanager returned more rows than totalCount; "
                    "no prices were changed."
                )
            offset += len(batch)
            if offset < total and len(batch) < page_size:
                raise reportable_error(
                    f"{what}: Vetmanager ended pagination before totalCount; "
                    "no prices were changed."
                )
            if offset >= total:
                return collected

    async def _rows_for_good(good_id: int, clinic_id: int) -> list[dict]:
        filters = [_filter_eq("good_id", good_id)]
        if clinic_id:
            filters.append(_filter_eq("clinic_id", clinic_id))
        return await _all_rows(
            "/rest/api/goodSaleParam", "goodSaleParam", filters,
            f"price rows of good {good_id}",
        )

    async def _count_rows(filters: list) -> int | None:
        """Сколько строк подходит под фильтр — без вычитывания самих строк.

        Этап 298.7. Число строк группы нужно **в превью**, где строки не
        читаются: их читает только запись. Обход по товару стоил бы запроса на
        товар — 57 запросов ради одного числа на группе 66 стенда `devtr6`.
        Апстрим принимает `IN` списком, и `totalCount` при `limit=1` отвечает
        на вопрос целиком.
        """
        payload = await crud_list(
            "/rest/api/goodSaleParam", limit=1, offset=0, filters=filters,
            allowed_filter_properties=FILTER_FIELDS_BY_ENTITY["goodSaleParam"],
        )
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        try:
            return int(data.get("totalCount"))
        except (TypeError, ValueError):
            # Finding внешнего ревью 06.09.2026. Считать длину пришедшего
            # списка здесь нельзя: запрос идёт с `limit=1`, и группа на 112
            # строк дала бы единицу — вариант выглядел бы проходящим. «Не
            # знаю» и «одна строка» должны различаться.
            return None

    async def _group_row_counts(
        good_ids: list[int], clinic_id: int
    ) -> tuple[int | None, int | None]:
        """(всего строк, из них пишущихся) по товарам группы.

        Пишущиеся считаются вычитанием строк с `price_formation='increase'`, а
        не отдельным условием «не increase»: оператор `!=` по этому полю мы не
        проверяли, а вычитание опирается только на равенство. Сходимость с тем,
        как считает запись, проверена на `devtr6` 06.09.2026: 114 всего, 2
        `increase`, и запись отказала ровно на 112.

        Пустой список товаров запроса не делает: `IN []` апстрим отдаёт 500
        (проверено там же), а `filters.in_` такой список и не построит.
        """
        if not good_ids:
            return 0, 0
        filters = [_filter_in("good_id", good_ids)]
        if clinic_id:
            filters.append(_filter_eq("clinic_id", clinic_id))
        total = await _count_rows(filters)
        derived = await _count_rows(filters + [_filter_eq("price_formation", "increase")])
        if total is None or derived is None:
            return None, None
        return total, max(total - derived, 0)

    async def _goods_in_group(group_id: int) -> list[dict]:
        return await _all_rows(
            "/rest/api/good", "good", [_filter_eq("group_id", group_id)],
            f"goods in group {group_id}",
        )

    @mcp.tool
    async def update_good_sale_price(
        sale_param_id: int,
        new_price: float = 0.0,
        change_percent: float = 0.0,
        scope: str = "row",
        clinic_id: int = 0,
        confirm: bool = False,
        expected_price: str = "",
    ) -> dict:
        """Change a sale price. Shows what would change and writes only on confirm.

        A price is visible to the clinic's own customers, so this tool does
        nothing by default: without `confirm=True` it returns a preview and
        sends no write request at all.

        A good does NOT have one price. `good_sale_param` holds a row per clinic
        and per sale unit, so the preview lists the update variants and how many
        rows each one touches. Rows where `price_formation` is `increase` derive
        their price from a markup: writing `price` there looks done and changes
        nothing, so such a row is refused.

        Args:
            sale_param_id: ID of the sale parameter row to start from
                (`get_good_sale_params` lists them for a good).
            new_price: Absolute new price. Not allowed for scope='group':
                one price for every good in a group is almost never meant.
            change_percent: Relative change, e.g. 10 raises by 10%, -5 lowers
                by 5%. Use this for a group. Mutually exclusive with new_price.
            scope: 'row' — this row only; 'good' — every price row of this good;
                'group' — every good in this good's group.
            clinic_id: Restrict 'good' or 'group' to a single clinic (0 = all).
            confirm: Must be true to actually write. Without it nothing changes.
            expected_price: Optional optimistic guard for a confirmed row update.
                The current price must still equal this value. Only valid with
                scope='row' and confirm=true; this is not an atomic CAS.
        """
        if scope not in _PRICE_SCOPES:
            raise ToolInputError(f"scope must be one of {list(_PRICE_SCOPES)}, got '{scope}'")
        if bool(new_price) == bool(change_percent):
            raise ToolInputError(
                "Pass exactly one of new_price or change_percent: "
                "two ways to say the same number means guessing which one was meant."
            )
        if new_price and scope == "group":
            raise ToolInputError(
                "scope='group' does not accept new_price: setting every good in a "
                "group to the same price is almost never intended. Use change_percent."
            )
        if new_price < 0 or (new_price == 0 and change_percent == 0):
            raise ToolInputError("new_price must be positive.")
        if expected_price and (scope != "row" or not confirm):
            raise ToolInputError(
                "expected_price is only valid with scope='row' and confirm=true."
            )

        row = _price_row(await crud_get_by_id(
            "/rest/api/goodSaleParam", sale_param_id,
            fresh=bool(confirm and expected_price),
        ))
        if str(row.get("price_formation") or "") == "increase":
            raise ToolInputError(
                f"Sale parameter {sale_param_id} derives its price from a markup "
                "(price_formation='increase'), so writing price would change nothing. "
                "Change the markup instead."
            )

        current = _money(row.get("price"), field="price")
        if expected_price:
            expected = _caller_number(expected_price, field="expected_price")
            if current != expected:
                raise ToolInputError(
                    f"expected_price does not match the current price of sale parameter "
                    f"{sale_param_id}; current price is {current}. No price was changed. "
                    "Read the row again before retrying."
                )
        target = _apply_change(current, new_price, change_percent)

        good_id = int(row.get("good_id") or 0)
        good = {}
        if good_id:
            good_payload = await crud_get_by_id("/rest/api/good", good_id)
            good_data = good_payload.get("data", {}) if isinstance(good_payload, dict) else {}
            good = good_data.get("good") if isinstance(good_data, dict) else {}
            good = good if isinstance(good, dict) else {}
        good_rows = await _rows_for_good(good_id, clinic_id) if good_id else [row]
        group_id = int(good.get("group_id") or 0)
        # Товары группы нужны превью и групповой записи. Записи одной
        # строки они не нужны — finding внешнего ревью 06.09.2026: путь
        # записи не должен зависеть от запросов, которых не использует.
        needs_group = not confirm or scope == "group"
        group_goods = await _goods_in_group(group_id) if group_id and needs_group else []

        if not confirm:
            # Вызов должен повторяться буквально: без самой величины он падает на
            # «Pass exactly one of new_price or change_percent» (внешнее ревью).
            _change_args = (
                {"new_price": new_price} if new_price else {"change_percent": change_percent}
            )
            # Этап 298.7. Вариант называет то, чем меряется предел, — строки. До
            # этого групповой вариант выдавал число товаров и готовый вызов, а
            # предел считал строки: на группе 66 стенда `devtr6` превью предлагало
            # вызов, который сам же и отклонял (57 товаров, 112 строк, предел 50).
            group_ids = [int(member.get("id") or 0) for member in group_goods if member.get("id")]
            group_rows_total, group_rows_writable = await _group_row_counts(group_ids, clinic_id)
            good_writable = _writable_count(good_rows)

            def _variant(
                variant_scope: str, *, rows: int | None, writable: int | None,
                note: str, call, **extra
            ) -> dict:
                # Неизвестное число строк закрывает вариант так же, как
                # превышение: предложить вызов, о котором нечего сказать,
                # значит переложить проверку предела на клинику.
                exceeds = writable is None or writable > _PRICE_UPDATE_ROW_LIMIT
                if writable is None:
                    note = (
                        f"{note} Не предлагается: апстрим не вернул totalCount, "
                        "и число строк неизвестно."
                    )
                elif exceeds:
                    note = (
                        f"{note} Не выполнится: {writable} строк при пределе "
                        f"{_PRICE_UPDATE_ROW_LIMIT} за вызов. Сузьте до клиники "
                        "(`clinic_id`) или делайте такую переоценку отчётом и руками."
                    )
                return {
                    "scope": variant_scope,
                    "rows": rows,
                    "writable_rows": writable,
                    "exceeds_limit": exceeds,
                    "note": note,
                    "call": None if exceeds else call,
                    **extra,
                }

            variants = [
                _variant(
                    "row", rows=1, writable=_writable_count([row]),
                    note=(
                        f"Только эта строка: клиника {row.get('clinic_id')}, "
                        f"единица продажи {row.get('unit_sale_id')}."
                    ),
                    call=dict(_change_args, sale_param_id=sale_param_id, scope="row", confirm=True),
                ),
                _variant(
                    "good", rows=len(good_rows), writable=good_writable,
                    note=(
                        f"Все строки цены товара {good_id}"
                        + (f" в клинике {clinic_id}." if clinic_id else " во всех клиниках.")
                    ),
                    call=dict(_change_args, sale_param_id=sale_param_id, scope="good", confirm=True),
                ),
                _variant(
                    "group", rows=group_rows_total, writable=group_rows_writable,
                    goods=len(group_goods),
                    note=(
                        (
                            f"Все товары группы {group_id} — только процентом."
                            if change_percent
                            # Finding второго прогона ревью 06.09.2026: вызов с
                            # «укажите процент» внутри — записка, а не вызов, и
                            # повтор падает на типе. Непустой `call` означает
                            # «выполнимо», значит здесь его быть не должно.
                            else f"Все товары группы {group_id} — только процентом: "
                                 "повторите вызов с `change_percent`."
                        )
                        if group_id else "Группа у товара не указана."
                    ),
                    call=(
                        {
                            "sale_param_id": sale_param_id, "scope": "group",
                            "change_percent": change_percent, "confirm": True,
                        }
                        if group_ids and change_percent else None
                    ),
                ),
            ]

            preview = {
                "applied": False,
                "sale_param_id": sale_param_id,
                "good_id": good_id,
                "good_title": good.get("title"),
                "clinic_id": row.get("clinic_id"),
                "unit_sale_id": row.get("unit_sale_id"),
                "status": row.get("status"),
                "price_formation": row.get("price_formation"),
                "current_price": row.get("price"),
                "new_price": str(target),
                "sale_band": _sale_band(target, row),
                "scope": scope,
                "variants": variants,
                "next_step": (
                    "Ничего не изменено. Повторите вызов с confirm=true и нужным scope."
                ),
            }
            return preview


        if scope == "row":
            targets = [row]
        elif scope == "good":
            targets = good_rows
        else:
            targets = []
            for member in group_goods:
                member_id = int(member.get("id") or 0)
                if member_id:
                    targets.extend(await _rows_for_good(member_id, clinic_id))

        writable = [item for item in targets if _is_writable(item)]
        skipped_derived = [item.get("id") for item in targets if not _is_writable(item)]
        if len(writable) > _PRICE_UPDATE_ROW_LIMIT:
            raise ToolInputError(
                f"This variant touches {len(writable)} price rows, above the "
                f"{_PRICE_UPDATE_ROW_LIMIT}-row limit for a single call. A repricing "
                "that large is done from a report and by hand, not by one agent call."
            )

        plan: list[dict] = []
        for item in writable:
            item_id = int(item.get("id") or 0)
            if not item_id:
                continue
            before = _money(item.get("price"), field="price")
            item_target = target if new_price else _apply_change(before, 0, change_percent)
            plan.append({
                "sale_param_id": item_id,
                "clinic_id": item.get("clinic_id"),
                "before": item.get("price"),
                "target": str(item_target),
            })

        updated: list[dict] = []
        acknowledged_writes = 0

        def _reason(exc: Exception) -> dict:
            status_code = getattr(exc, "status_code", None)
            if isinstance(status_code, int):
                return {
                    "code": f"http_{status_code}",
                    "message": "Vetmanager rejected the price update.",
                }
            name = type(exc).__name__.lower()
            if "timeout" in name:
                return {"code": "timeout", "message": "Vetmanager did not answer in time."}
            if any(word in name for word in ("connect", "resolution", "tls")):
                return {"code": "connection", "message": "Vetmanager could not be reached."}
            if name == "toolerror":
                return {
                    "code": "malformed_response",
                    "message": "Vetmanager returned an unusable verification response.",
                }
            return {"code": "upstream_error", "message": "Vetmanager update failed."}

        def _incomplete(index: int, *, phase: str, reason: dict, acknowledged: bool,
                        write_state: str) -> dict:
            failed = {
                **plan[index],
                "phase": phase,
                "reason": reason,
                "write_acknowledged": acknowledged,
                "write_state": write_state,
            }
            untouched = plan[index + 1:]
            resume_calls = [
                {
                    "sale_param_id": item["sale_param_id"],
                    "scope": "row",
                    "new_price": item["target"],
                    "expected_price": item["before"],
                    "confirm": True,
                }
                for item in untouched
            ]
            first = updated[0] if updated else {}
            return {
                "applied": False,
                "complete": False,
                "partially_applied": acknowledged_writes > 0,
                "status": "partial" if acknowledged_writes > 0 else "failed",
                "scope": scope,
                "updated_rows": len(updated),
                "acknowledged_writes": acknowledged_writes,
                "sale_param_id": sale_param_id,
                "before": first.get("before"),
                "after": first.get("after"),
                "updated": updated,
                "failed": failed,
                "untouched": untouched,
                "resume_calls": resume_calls,
                "retry_policy": {
                    "repeat_same_percentage_call": False,
                    "safe_completion": "read_failed_then_apply_absolute_targets",
                },
                "next_step": (
                    "Do not repeat the original percentage repricing. Read the failed row, "
                    "apply its absolute target only if still needed, then run resume_calls."
                ),
                "skipped_derived_price_rows": skipped_derived,
            }

        for index, item in enumerate(plan):
            item_id = item["sale_param_id"]
            try:
                await crud_update(
                    "/rest/api/goodSaleParam", item_id, {"price": item["target"]}
                )
                acknowledged_writes += 1
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                return _incomplete(
                    index,
                    phase="put",
                    reason=_reason(exc),
                    acknowledged=False,
                    write_state="not_written" if status_code == 404 else "unknown",
                )

            try:
                # «Стало» читается заново: эхо запроса подтверждает только то,
                # что мы его отправили.
                after = _price_row(await crud_get_by_id("/rest/api/goodSaleParam", item_id))
                after_price = _money(after.get("price"), field="price")
            except Exception as exc:
                return _incomplete(
                    index, phase="verify", reason=_reason(exc),
                    acknowledged=True, write_state="unknown",
                )
            if after_price != Decimal(item["target"]):
                return _incomplete(
                    index,
                    phase="verify",
                    reason={
                        "code": "verification_mismatch",
                        "message": "The read-back price did not match the requested target.",
                    },
                    acknowledged=True,
                    write_state="unknown",
                )
            updated.append({
                "sale_param_id": item_id,
                "clinic_id": item["clinic_id"],
                "before": item["before"],
                "target": item["target"],
                "after": after.get("price"),
            })

        first = updated[0] if updated else {}
        return {
            "applied": True,
            "complete": True,
            "partially_applied": False,
            "status": "completed",
            "scope": scope,
            "updated_rows": len(updated),
            "acknowledged_writes": acknowledged_writes,
            "sale_param_id": sale_param_id,
            "before": first.get("before"),
            "after": first.get("after"),
            "updated": updated,
            "skipped_derived_price_rows": skipped_derived,
        }

    @mcp.tool
    async def update_supplier(
        supplier_id: int,
        company_name: str = "",
        contact_person: str = "",
        phone: str = "",
        mail: str = "",
        address: str = "",
        note: str = "",
        status: str = "",
    ) -> dict:
        """Update an existing supplier/counterparty.

        Note: Vetmanager API does not allow deleting suppliers via REST.

        Args:
            supplier_id: ID of the supplier to update.
            company_name: Updated company name (leave empty to keep current).
            contact_person: Updated contact person name.
            phone: Updated phone number.
            mail: Updated email address.
            address: Updated postal address.
            note: Updated notes.
            status: Updated status.
        """
        payload: dict = {}
        if company_name:
            payload["company_name"] = company_name
        if contact_person:
            payload["contact_person"] = contact_person
        if phone:
            payload["phone"] = phone
        if mail:
            payload["mail"] = mail
        if address:
            payload["address"] = address
        if note:
            payload["note"] = note
        if status:
            payload["status"] = status
        return await crud_update("/rest/api/Suppliers", supplier_id, payload)

    @mcp.tool
    async def get_good_stock_balance(
        good_id: int,
        clinic_id: int = 1,
    ) -> dict:
        """Get the current stock balance (remaining quantity) for a specific good in the warehouse.

        Uses the dedicated RestOfGoodInWarehouse endpoint which returns the actual
        remaining quantity accounting for all receipts and write-offs.
        Both good_id and clinic_id are required by the API.

        Args:
            good_id: ID of the good/product to check stock for.
            clinic_id: Clinic/branch ID (default 1 — main clinic).
        """
        result = await VetmanagerClient().get(
            "/rest/api/stores/RestOfGoodInWarehouse/",
            params={"good_id": good_id, "clinic_id": clinic_id},
        )
        quantity_str = (
            result.get("data", {})
            .get("rest_good_in_warehouse", {})
            .get("quantity", "0")
        )
        return {
            "good_id": good_id,
            "clinic_id": clinic_id,
            "quantity": float(quantity_str),
            "quantity_str": quantity_str,
            "raw": result,
        }
