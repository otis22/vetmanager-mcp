"""Warehouse/inventory entity tools: GoodGroup, GoodSaleParam, PartyAccount,
PartyAccountDoc, StoreDocument, Suppliers."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastmcp import FastMCP
from exceptions import ToolInputError, reportable_error
from filters import FILTER_FIELDS_BY_ENTITY, eq as _filter_eq, in_ as _filter_in
from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update
from validators import LimitParam
from vetmanager_client import VetmanagerClient

# Этап 298. Сколько строк цены один вызов вправе переписать. Больше — работа
# для отчёта и рук клиники, а не для одного вызова агента: цену видят клиенты,
# и откатывать массовую ошибку придётся тоже руками.
_PRICE_UPDATE_ROW_LIMIT = 50
# Сколько строк инструмент вообще согласен прочитать, прежде чем сказать, что
# такая переоценка делается не одним вызовом.
_PRICE_UPDATE_FETCH_LIMIT = 500
_PRICE_SCOPES = ("row", "good", "group")
_MONEY = Decimal("0.01")


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
        offset = 0
        while True:
            payload = await crud_list(
                endpoint, limit=100, offset=offset, filters=filters,
                allowed_filter_properties=FILTER_FIELDS_BY_ENTITY[key],
            )
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            rows = data.get(key) if isinstance(data, dict) else None
            batch = [row for row in rows or [] if isinstance(row, dict)]
            collected.extend(batch)
            try:
                total = int(data.get("totalCount"))
            except (TypeError, ValueError):
                total = len(collected)
            if total > _PRICE_UPDATE_FETCH_LIMIT:
                raise ToolInputError(
                    f"{what}: Vetmanager reports {total} records, above the "
                    f"{_PRICE_UPDATE_FETCH_LIMIT} this tool will read. A repricing that "
                    "wide is done from a report and by hand — a partial pass over prices "
                    "is worse than none."
                )
            offset += len(batch)
            if not batch or offset >= total:
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

        row = _price_row(await crud_get_by_id("/rest/api/goodSaleParam", sale_param_id))
        if str(row.get("price_formation") or "") == "increase":
            raise ToolInputError(
                f"Sale parameter {sale_param_id} derives its price from a markup "
                "(price_formation='increase'), so writing price would change nothing. "
                "Change the markup instead."
            )

        current = _money(row.get("price"), field="price")
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

        updated: list[dict] = []
        for item in writable:
            item_id = int(item.get("id") or 0)
            if not item_id:
                continue
            before = _money(item.get("price"), field="price")
            item_target = target if new_price else _apply_change(before, 0, change_percent)
            await crud_update("/rest/api/goodSaleParam", item_id, {"price": str(item_target)})
            # «Стало» читается заново: эхо запроса подтверждает только то, что мы
            # его отправили.
            after = _price_row(await crud_get_by_id("/rest/api/goodSaleParam", item_id))
            updated.append({
                "sale_param_id": item_id,
                "clinic_id": item.get("clinic_id"),
                "before": item.get("price"),
                "after": after.get("price"),
            })

        first = updated[0] if updated else {}
        return {
            "applied": True,
            "scope": scope,
            "updated_rows": len(updated),
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
