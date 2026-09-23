from backend.models.purchase import Supplier, SupplierAssessment


class SupplierService:
    def assess(self, supplier: Supplier) -> SupplierAssessment:
        has_history = supplier.successful_deliveries is not None
        delivery_rate = None
        late_rate = None
        if has_history:
            total = supplier.successful_deliveries + (supplier.late_deliveries or 0)
            if total:
                delivery_rate = supplier.successful_deliveries / total
                late_rate = (supplier.late_deliveries or 0) / total

        facts = []
        if supplier.defect_rate is not None:
            facts.append("defect rate is present")
        if supplier.average_delay_days is not None:
            facts.append("average delivery delay is present")
        evidence_note = (
            "DEMO rating/reliability fields are available; verified delivery, defect and return history is absent."
            if not has_history and supplier.defect_rate is None
            else "Supplier history is limited to the fields listed; no missing metric was inferred."
        )
        return SupplierAssessment(
            supplier_id=supplier.id,
            supplier_name=supplier.name,
            data_status="available" if has_history or facts else "insufficient_data",
            delivery_rate=delivery_rate,
            late_delivery_rate=late_rate,
            average_delay_days=supplier.average_delay_days,
            defect_rate=supplier.defect_rate,
            return_rate=supplier.return_rate,
            demo_rating=supplier.rating,
            demo_reliability=supplier.reliability,
            evidence_note=evidence_note,
        )
