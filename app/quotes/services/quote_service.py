from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.audit.models.audit_event import ActorType
from app.audit.services.audit_service import AuditService
from app.organizations.repositories.organization_repository import OrganizationRepository
from app.quotes.models.quote import (
    QUOTE_TRANSITIONS,
    Quote,
    QuoteLineItem,
    QuoteLineItemCategory,
    QuoteStatus,
)
from app.quotes.repositories.quote_repository import QuoteRepository
from app.quotes.services.quote_calculator_service import (
    QuoteCalculationEstimate,
    QuoteCalculatorConfig,
    QuoteCalculatorInput,
    QuoteCalculatorService,
)
from app.shared.errors.exceptions import ConflictError, NotFoundError
from app.shared.notifications.factory import get_email_sender
from app.shared.notifications.smtp_email_sender import EmailNotConfiguredError


def _round2(val: Decimal | str | float | int) -> Decimal:
    return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class QuoteService:
    """Core domain service for JEXA Admin quotation management."""

    def __init__(
        self,
        quote_repo: QuoteRepository,
        org_repo: OrganizationRepository,
        audit_service: AuditService | None = None,
        calculator_service: QuoteCalculatorService | None = None,
    ) -> None:
        self.quote_repo = quote_repo
        self.org_repo = org_repo
        self.audit_service = audit_service
        self.calculator_service = calculator_service or QuoteCalculatorService(
            QuoteCalculatorConfig()
        )

    def calculate_estimate(self, inputs: QuoteCalculatorInput) -> QuoteCalculationEstimate:
        """Runs the transparent estimation engine without persisting any quote."""
        return self.calculator_service.calculate(inputs)

    async def create_quote(
        self,
        *,
        organization_id: str,
        title: str,
        valid_until: datetime,
        currency: str = "INR",
        lead_id: str | None = None,
        voice_project_id: str | None = None,
        notes: str | None = None,
        terms: str | None = None,
        discount: Decimal = Decimal("0.00"),
        tax_rate: Decimal = Decimal("0.00"),
        included_voice_minutes: int = 0,
        additional_minute_rate: Decimal = Decimal("0.00"),
        estimated_setup_fee: Decimal | None = None,
        estimated_recurring_fee: Decimal | None = None,
        calculation_snapshot: dict[str, Any] | None = None,
        line_items_data: list[dict[str, Any]],
        created_by_user_id: str | None = None,
    ) -> Quote:
        org = await self.org_repo.get_by_id(organization_id)
        if org is None:
            raise NotFoundError("Organization not found.")

        quote_number = await self.quote_repo.generate_next_quote_number()

        # Build and compute line items
        line_items: list[QuoteLineItem] = []
        subtotal = Decimal("0.00")

        for idx, item in enumerate(line_items_data):
            qty = _round2(item.get("quantity", 1))
            unit_price = _round2(item.get("unit_price", 0))
            amount = _round2(qty * unit_price)
            subtotal += amount

            category = item.get("category", QuoteLineItemCategory.OTHER)
            if isinstance(category, str):
                category = QuoteLineItemCategory(category)

            line_items.append(
                QuoteLineItem(
                    category=category,
                    description=item["description"],
                    quantity=qty,
                    unit=item.get("unit", "unit"),
                    unit_price=unit_price,
                    amount=amount,
                    display_order=idx,
                )
            )

        # Discount handling
        applied_discount = _round2(max(Decimal("0.00"), discount))
        post_discount_subtotal = max(Decimal("0.00"), subtotal - applied_discount)

        # Tax handling
        tax_rate_dec = _round2(max(Decimal("0.00"), tax_rate))
        tax_amount = _round2(post_discount_subtotal * (tax_rate_dec / Decimal("100.00")))
        total = _round2(post_discount_subtotal + tax_amount)

        quote = Quote(
            organization_id=organization_id,
            lead_id=lead_id,
            voice_project_id=voice_project_id,
            quote_number=quote_number,
            title=title,
            status=QuoteStatus.DRAFT,
            currency=currency,
            subtotal=_round2(subtotal),
            discount=applied_discount,
            tax_rate=tax_rate_dec,
            tax_amount=tax_amount,
            total=total,
            valid_until=valid_until,
            notes=notes,
            terms=terms,
            estimated_setup_fee=_round2(estimated_setup_fee)
            if estimated_setup_fee is not None
            else None,
            estimated_recurring_fee=_round2(estimated_recurring_fee)
            if estimated_recurring_fee is not None
            else None,
            included_voice_minutes=included_voice_minutes,
            additional_minute_rate=_round2(additional_minute_rate),
            calculation_snapshot=calculation_snapshot,
            created_by_user_id=created_by_user_id,
            line_items=line_items,
        )

        quote = await self.quote_repo.create(quote)

        if self.audit_service:
            await self.audit_service.record(
                organization_id=organization_id,
                actor_id=created_by_user_id,
                actor_type=ActorType.AIVRA_ADMIN,
                action="quote.created",
                resource_type="quote",
                resource_id=quote.id,
            )

        return quote

    async def get_quote(self, quote_id: str) -> Quote:
        quote = await self.quote_repo.get_by_id(quote_id)
        if quote is None:
            raise NotFoundError("Quote not found.")
        return quote

    async def update_draft_quote(
        self,
        quote_id: str,
        *,
        title: str | None = None,
        valid_until: datetime | None = None,
        notes: str | None = None,
        terms: str | None = None,
        discount: Decimal | None = None,
        tax_rate: Decimal | None = None,
        included_voice_minutes: int | None = None,
        additional_minute_rate: Decimal | None = None,
        line_items_data: list[dict[str, Any]] | None = None,
        actor_id: str | None = None,
    ) -> Quote:
        quote = await self.get_quote(quote_id)
        if quote.status != QuoteStatus.DRAFT:
            raise ConflictError("Only draft quotes can be edited.")

        if title is not None:
            quote.title = title
        if valid_until is not None:
            quote.valid_until = valid_until
        if notes is not None:
            quote.notes = notes
        if terms is not None:
            quote.terms = terms
        if included_voice_minutes is not None:
            quote.included_voice_minutes = included_voice_minutes
        if additional_minute_rate is not None:
            quote.additional_minute_rate = _round2(additional_minute_rate)

        # Update line items if provided
        if line_items_data is not None:
            quote.line_items.clear()
            subtotal = Decimal("0.00")
            for idx, item in enumerate(line_items_data):
                qty = _round2(item.get("quantity", 1))
                unit_price = _round2(item.get("unit_price", 0))
                amount = _round2(qty * unit_price)
                subtotal += amount

                cat = item.get("category", QuoteLineItemCategory.OTHER)
                if isinstance(cat, str):
                    cat = QuoteLineItemCategory(cat)

                quote.line_items.append(
                    QuoteLineItem(
                        quote_id=quote.id,
                        category=cat,
                        description=item["description"],
                        quantity=qty,
                        unit=item.get("unit", "unit"),
                        unit_price=unit_price,
                        amount=amount,
                        display_order=idx,
                    )
                )
            quote.subtotal = _round2(subtotal)

        if discount is not None:
            quote.discount = _round2(max(Decimal("0.00"), discount))
        if tax_rate is not None:
            quote.tax_rate = _round2(max(Decimal("0.00"), tax_rate))

        # Recalculate totals
        post_discount = max(Decimal("0.00"), quote.subtotal - quote.discount)
        quote.tax_amount = _round2(post_discount * (quote.tax_rate / Decimal("100.00")))
        quote.total = _round2(post_discount + quote.tax_amount)

        await self.quote_repo.session.flush()

        if self.audit_service:
            await self.audit_service.record(
                organization_id=quote.organization_id,
                actor_id=actor_id,
                actor_type=ActorType.AIVRA_ADMIN,
                action="quote.updated",
                resource_type="quote",
                resource_id=quote.id,
            )

        return quote

    async def send_quote(
        self,
        quote_id: str,
        *,
        recipient_email: str | None = None,
        recipient_name: str | None = None,
        actor_id: str | None = None,
    ) -> tuple[Quote, bool, str | None]:
        """Marks quote as SENT and attempts delivery if SMTP is configured.

        Never pretends an email was sent if SMTP is unconfigured.
        """
        quote = await self.get_quote(quote_id)
        QUOTE_TRANSITIONS.assert_transition_allowed(quote.status, QuoteStatus.SENT)

        quote.status = QuoteStatus.SENT
        quote.sent_at = datetime.now(UTC)

        email_sent = False
        email_error: str | None = None

        if recipient_email:
            try:
                email_sender = get_email_sender()
                body = (
                    f"Dear {recipient_name or 'Valued Customer'},\n\n"
                    f"Your JEXA quotation ({quote.quote_number}) has been prepared:\n"
                    f"{quote.title}\n\n"
                    f"Total: {quote.currency} {quote.total:,.2f}\n"
                    f"Valid Until: {quote.valid_until.strftime('%Y-%m-%d')}\n\n"
                    f"Thank you for choosing JEXA.\n"
                )
                await email_sender.send(
                    to=[recipient_email],
                    subject=f"JEXA Quote {quote.quote_number} — {quote.title}",
                    body=body,
                )
                email_sent = True
            except EmailNotConfiguredError:
                email_sent = False
                email_error = (
                    "Email delivery unconfigured (SMTP_HOST missing). Status updated to Sent."
                )
            except Exception as e:
                email_sent = False
                email_error = f"Failed to send email: {e!s}"

        await self.quote_repo.session.flush()

        if self.audit_service:
            await self.audit_service.record(
                organization_id=quote.organization_id,
                actor_id=actor_id,
                actor_type=ActorType.AIVRA_ADMIN,
                action="quote.sent",
                resource_type="quote",
                resource_id=quote.id,
            )

        return quote, email_sent, email_error

    async def transition_status(
        self,
        quote_id: str,
        *,
        target_status: QuoteStatus,
        rejection_reason: str | None = None,
        actor_id: str | None = None,
    ) -> Quote:
        quote = await self.get_quote(quote_id)
        QUOTE_TRANSITIONS.assert_transition_allowed(quote.status, target_status)

        quote.status = target_status
        now = datetime.now(UTC)

        if target_status == QuoteStatus.ACCEPTED:
            quote.accepted_at = now
        elif target_status == QuoteStatus.REJECTED:
            quote.rejected_at = now
            quote.rejection_reason = rejection_reason

        await self.quote_repo.session.flush()

        if self.audit_service:
            await self.audit_service.record(
                organization_id=quote.organization_id,
                actor_id=actor_id,
                actor_type=ActorType.AIVRA_ADMIN,
                action=f"quote.{target_status.value}",
                resource_type="quote",
                resource_id=quote.id,
            )

        return quote
