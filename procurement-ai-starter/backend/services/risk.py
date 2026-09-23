from backend.models.purchase import PurchasePlan, PurchaseRequest, RiskAssessment


class RiskService:
    """Produces evidence-backed risks; unknown data stays unknown."""

    def assess(self, request: PurchaseRequest, plan: PurchasePlan) -> list[RiskAssessment]:
        risks: list[RiskAssessment] = []
        if not plan.lines:
            risks.append(
                RiskAssessment(
                    risk_type="availability",
                    severity="high",
                    reason="No eligible offer was selected for this request.",
                    evidence=[f"Requested {request.quantity}; planned {plan.quantity_planned} units."],
                )
            )
            return risks

        insufficient = [item for item in plan.supplier_assessments if item.data_status == "insufficient_data"]
        if insufficient:
            risks.append(
                RiskAssessment(
                    risk_type="supplier",
                    severity="unknown",
                    reason="Supplier performance cannot be scored without verified delivery and quality history.",
                    evidence=[
                        f"Supplier {item.supplier_id} ({item.supplier_name}) has no verified history."
                        for item in insufficient
                    ],
                )
            )

        if request.max_delivery_days is not None:
            late = [line for line in plan.lines if line.delivery_days > request.max_delivery_days]
            if late:
                risks.append(
                    RiskAssessment(
                        risk_type="delivery",
                        severity="high",
                        reason="Selected offer lead time exceeds the requested delivery limit.",
                        evidence=[
                            f"Offer {line.offer_id}: {line.delivery_days} days vs limit {request.max_delivery_days}."
                            for line in late
                        ],
                    )
                )
        else:
            risks.append(
                RiskAssessment(
                    risk_type="delivery",
                    severity="unknown",
                    reason="Offer lead times are available, but no execution history or user deadline is available.",
                    evidence=[
                        f"Selected offer lead times: {', '.join(str(line.delivery_days) for line in plan.lines)} days."
                    ],
                )
            )

        comparisons = {item.offer_id: item for item in plan.price_summary.history_comparisons}
        for line in plan.lines:
            comparison = comparisons.get(line.offer_id)
            if comparison is None or comparison.status == "unknown":
                evidence = [f"Offer {line.offer_id}: fewer than 3 matching recent observation dates."]
                if comparison is not None:
                    evidence.append(
                        f"DEMO DATA; {comparison.sample_count} observations in "
                        f"{comparison.window_start}–{comparison.as_of}."
                    )
                risks.append(RiskAssessment(
                    risk_type="price", severity="unknown", entity_id=str(line.offer_id),
                    reason="Недостаточно свежей истории для сравнения цены.", evidence=evidence,
                ))
                continue
            reasons = {
                "above_history": "Цена выше исторической медианы на величину не меньше порога аномалии.",
                "below_history": "Цена ниже исторической медианы на величину не меньше порога; условия предложения требуют проверки.",
                "within_range": "Отклонение цены от исторической медианы находится в пределах заданного порога.",
            }
            risks.append(RiskAssessment(
                risk_type="price", severity={"above_history": "high", "below_history": "medium", "within_range": "low"}[comparison.status],
                entity_id=str(line.offer_id), reason=reasons[comparison.status],
                evidence=[
                    "DEMO DATA: synthetic observations, not verified market price history.",
                    f"Offer {line.offer_id}: current {comparison.current_unit_price} {comparison.currency}; "
                    f"historical median {comparison.median_historical_unit_price} {comparison.currency}; "
                    f"deviation {comparison.deviation_percent}%; threshold ±{comparison.anomaly_threshold_percent}%.",
                    f"{comparison.sample_count} dates from {comparison.history_from} to {comparison.history_to}; "
                    f"analysis window {comparison.window_start}–{comparison.as_of}.",
                ],
            ))

        if plan.quantity_planned < request.quantity:
            risks.append(
                RiskAssessment(
                    risk_type="availability",
                    severity="high",
                    reason="Available offers do not cover the requested quantity.",
                    evidence=[f"Requested {request.quantity}; planned {plan.quantity_planned} units."],
                )
            )
        else:
            risks.append(
                RiskAssessment(
                    risk_type="availability",
                    severity="unknown",
                    reason="Offer quantities are catalogue snapshots and are not reserved by this draft.",
                    evidence=["No stock reservation was made; supplier availability may change."],
                )
            )

        supplier_quantities: dict[int, int] = {}
        for line in plan.lines:
            supplier_quantities[line.supplier_id] = supplier_quantities.get(line.supplier_id, 0) + line.quantity
        largest_share = max(supplier_quantities.values()) / max(plan.quantity_planned, 1)
        if len(supplier_quantities) == 1:
            risks.append(
                RiskAssessment(
                    risk_type="single_supplier",
                    severity="medium",
                    reason="The plan depends on one supplier.",
                    evidence=[f"Supplier {next(iter(supplier_quantities))} covers all {plan.quantity_planned} units."],
                    entity_id=str(next(iter(supplier_quantities))),
                )
            )
        elif largest_share >= 0.8:
            supplier_id = max(supplier_quantities, key=supplier_quantities.get)
            risks.append(
                RiskAssessment(
                    risk_type="concentration",
                    severity="high",
                    reason="At least 80% of the planned quantity is concentrated with one supplier.",
                    evidence=[f"Supplier {supplier_id} covers {largest_share:.1%} of planned quantity."],
                    entity_id=str(supplier_id),
                )
            )

        return risks
