from dataclasses import dataclass
from decimal import Decimal

from backend.models.purchase import InvoiceFinding, InvoiceSubmission, PurchaseOrderItemRecord


@dataclass(frozen=True)
class EvaluatedInvoiceLine:
    order_item_id: int
    quantity: int
    unit_price: Decimal
    line_total: Decimal


@dataclass(frozen=True)
class InvoiceEvaluation:
    status: str
    findings: list[InvoiceFinding]
    lines: list[EvaluatedInvoiceLine]


class InvoiceReconciliationService:
    """Deterministic three-way invoice checks against order and manual receiving records."""

    def evaluate(
        self,
        submission: InvoiceSubmission,
        order_items: list[PurchaseOrderItemRecord],
        received_quantities: dict[int, tuple[int, int]],
        order_currency: str,
    ) -> InvoiceEvaluation:
        item_by_id = {item.id: item for item in order_items}
        findings: list[InvoiceFinding] = []
        lines: list[EvaluatedInvoiceLine] = []
        computed_subtotal = Decimal("0")
        pending_receiving = False

        if submission.currency != order_currency:
            findings.append(InvoiceFinding(
                code="invoice_currency_mismatch", severity="error",
                message=f"Счёт в {submission.currency}, заказ в {order_currency}.",
            ))

        for requested in submission.items:
            order_item = item_by_id.get(requested.order_item_id)
            if order_item is None:
                raise ValueError(f"Order item {requested.order_item_id} does not belong to this order")
            if order_item.supplier_id != submission.supplier_id:
                raise ValueError(f"Order item {requested.order_item_id} belongs to another supplier")
            line_total = requested.unit_price * requested.quantity
            computed_subtotal += line_total
            lines.append(EvaluatedInvoiceLine(
                order_item_id=requested.order_item_id,
                quantity=requested.quantity,
                unit_price=requested.unit_price,
                line_total=line_total,
            ))
            if requested.quantity > order_item.quantity:
                findings.append(InvoiceFinding(
                    code="invoice_quantity_exceeds_order", severity="error",
                    message=f"В счёте больше единиц, чем в строке заказа ({order_item.quantity}).",
                    order_item_id=requested.order_item_id,
                ))
            if requested.unit_price != order_item.unit_price:
                findings.append(InvoiceFinding(
                    code="invoice_unit_price_mismatch", severity="error",
                    message=f"Цена в счёте отличается от цены заказа ({order_item.unit_price}).",
                    order_item_id=requested.order_item_id,
                ))
            physically_received, accepted = received_quantities.get(requested.order_item_id, (0, 0))
            if requested.quantity > physically_received:
                pending_receiving = True
                findings.append(InvoiceFinding(
                    code="invoice_quantity_exceeds_received", severity="warning",
                    message=(f"Получено {physically_received} из {requested.quantity} единиц по счёту; "
                             "нужна приёмка оставшегося количества."),
                    order_item_id=requested.order_item_id,
                ))
            elif requested.quantity > accepted:
                findings.append(InvoiceFinding(
                    code="invoice_includes_damaged_units", severity="error",
                    message=f"Счёт включает повреждённые или не принятые единицы; принято {accepted}.",
                    order_item_id=requested.order_item_id,
                ))

        if computed_subtotal != submission.subtotal:
            findings.append(InvoiceFinding(
                code="invoice_subtotal_mismatch", severity="error",
                message=f"Сумма строк {computed_subtotal} не совпадает с subtotal счёта {submission.subtotal}.",
            ))
        computed_total = submission.subtotal + submission.tax_amount + submission.shipping_amount
        if computed_total != submission.total_amount:
            findings.append(InvoiceFinding(
                code="invoice_total_mismatch", severity="error",
                message=(f"Subtotal + налоги + доставка равны {computed_total}, "
                         f"а в счёте указано {submission.total_amount}."),
            ))

        has_errors = any(finding.severity == "error" for finding in findings)
        status = "VARIANCE" if has_errors else "PENDING_RECEIVING" if pending_receiving else "MATCHED"
        if status == "MATCHED":
            findings.append(InvoiceFinding(
                code="invoice_three_way_match", severity="info",
                message="Поставщик, строки заказа, цены, количество приёмки и суммы счёта совпали.",
            ))
        elif status == "PENDING_RECEIVING":
            findings.append(InvoiceFinding(
                code="invoice_waiting_for_receipt", severity="info",
                message="Счёт сохранён; повторная сверка доступна после ручной приёмки оставшихся единиц.",
            ))
        return InvoiceEvaluation(status=status, findings=findings, lines=lines)
