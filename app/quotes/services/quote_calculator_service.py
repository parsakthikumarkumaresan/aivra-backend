from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.quotes.models.quote import QuoteLineItemCategory


def _money(val: int | float | str | Decimal) -> Decimal:
    """Rounds values to standard 2-decimal money format."""
    return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class QuoteCalculatorConfig:
    """Configurable estimation parameters for the internal quote calculator.

    These parameters serve ONLY as internal baseline estimation heuristics.
    They are NOT hardcoded final pricing laws; the Admin has complete
    authority to override any estimated line item, quantity, or rate.
    """

    currency: str = "INR"

    # Implementation / Setup heuristics
    base_implementation_fee: Decimal = field(default_factory=lambda: Decimal("50000.00"))
    fee_per_additional_language: Decimal = field(default_factory=lambda: Decimal("15000.00"))
    workflow_complexity_fee: dict[str, Decimal] = field(
        default_factory=lambda: {
            "standard": Decimal("0.00"),
            "advanced": Decimal("20000.00"),
            "enterprise": Decimal("45000.00"),
        }
    )
    fee_per_integration: Decimal = field(default_factory=lambda: Decimal("15000.00"))
    fee_per_custom_tool: Decimal = field(default_factory=lambda: Decimal("10000.00"))
    knowledge_base_setup_fee: Decimal = field(default_factory=lambda: Decimal("10000.00"))

    # Recurring platform / maintenance heuristics
    base_platform_monthly_fee: Decimal = field(default_factory=lambda: Decimal("10000.00"))
    support_tier_monthly_fee: dict[str, Decimal] = field(
        default_factory=lambda: {
            "standard": Decimal("0.00"),
            "priority": Decimal("5000.00"),
            "dedicated": Decimal("15000.00"),
        }
    )
    monthly_fee_per_phone_number: Decimal = field(default_factory=lambda: Decimal("1500.00"))

    # Indicative usage rate heuristics (volume-scaled internal estimates)
    # [(min_monthly_minutes, indicative_rate_per_min)]
    indicative_rate_tiers: list[tuple[int, Decimal]] = field(
        default_factory=lambda: [
            (0, Decimal("2.50")),
            (2500, Decimal("2.25")),
            (5000, Decimal("2.00")),
            (10000, Decimal("1.75")),
            (25000, Decimal("1.50")),
        ]
    )


@dataclass
class QuoteCalculatorInput:
    """Inputs collected during discovery / VoiceProject requirements,
    along with optional configurable pricing heuristic parameters.

    IMPORTANT: Any defaults here are purely illustrative heuristics.
    They do NOT represent fixed commercial pricing. The Admin retains
    complete authority over final quoted amounts and line items.
    """

    monthly_calls: int = 1000
    avg_call_duration_minutes: Decimal = field(default_factory=lambda: Decimal("2.5"))
    languages_count: int = 1
    workflow_complexity: str = "standard"  # standard, advanced, enterprise
    integrations_count: int = 0
    custom_tools_count: int = 0
    knowledge_docs_count: int = 0
    telephony_numbers_count: int = 1
    support_tier: str = "standard"  # standard, priority, dedicated
    currency: str = "INR"

    # Configurable baseline pricing parameters (Admin controlled)
    target_minute_rate: Decimal | None = None
    base_implementation_fee: Decimal | None = None
    base_platform_monthly_fee: Decimal | None = None
    fee_per_additional_language: Decimal | None = None
    fee_per_integration: Decimal | None = None


@dataclass
class SuggestedLineItem:
    category: QuoteLineItemCategory
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    amount: Decimal


@dataclass
class QuoteCalculationEstimate:
    """Produced estimate for admin review and commercial adjustment."""

    estimated_setup_fee: Decimal
    estimated_recurring_fee: Decimal
    estimated_total_monthly_minutes: int
    recommended_included_minutes: int
    indicative_minute_rate: Decimal
    suggested_line_items: list[SuggestedLineItem]
    calculation_breakdown: dict[str, Any]
    disclaimer: str = (
        "Internal baseline estimate only. Final commercial quotation, line items, and prices "
        "are strictly determined and controlled by the JEXA Admin."
    )


class QuoteCalculatorService:
    """Decoupled internal quotation engine.

    Takes discovery/technical requirements and applies configurable
    estimation rules to produce suggested line items and commercial totals.
    """

    def __init__(self, config: QuoteCalculatorConfig | None = None) -> None:
        self.config = config or QuoteCalculatorConfig()

    def calculate(self, inputs: QuoteCalculatorInput) -> QuoteCalculationEstimate:
        cfg = self.config

        # 1. Volume calculation
        duration = (
            inputs.avg_call_duration_minutes
            if inputs.avg_call_duration_minutes > 0
            else Decimal("1.0")
        )
        total_monthly_minutes = int(Decimal(str(inputs.monthly_calls)) * duration)

        # Round up recommended starter minutes to nearest 500 or 1000
        if total_monthly_minutes <= 500:
            recommended_included = 500
        elif total_monthly_minutes <= 1000:
            recommended_included = 1000
        elif total_monthly_minutes <= 2500:
            recommended_included = 2500
        elif total_monthly_minutes <= 5000:
            recommended_included = 5000
        else:
            recommended_included = (total_monthly_minutes // 1000) * 1000

        # Indicative minute rate: Admin configured override takes precedence, otherwise volume tiers
        if inputs.target_minute_rate is not None and inputs.target_minute_rate > Decimal("0.00"):
            indicative_rate = inputs.target_minute_rate
        else:
            indicative_rate = cfg.indicative_rate_tiers[0][1]
            for threshold, rate in cfg.indicative_rate_tiers:
                if total_monthly_minutes >= threshold:
                    indicative_rate = rate

        # Configurable fees with fallback to baseline defaults
        impl_fee = (
            inputs.base_implementation_fee
            if inputs.base_implementation_fee is not None
            else cfg.base_implementation_fee
        )
        lang_fee = (
            inputs.fee_per_additional_language
            if inputs.fee_per_additional_language is not None
            else cfg.fee_per_additional_language
        )
        int_fee = (
            inputs.fee_per_integration
            if inputs.fee_per_integration is not None
            else cfg.fee_per_integration
        )
        platform_fee = (
            inputs.base_platform_monthly_fee
            if inputs.base_platform_monthly_fee is not None
            else cfg.base_platform_monthly_fee
        )

        # 2. Setup items calculation
        suggested_items: list[SuggestedLineItem] = []

        # Base implementation
        suggested_items.append(
            SuggestedLineItem(
                category=QuoteLineItemCategory.IMPLEMENTATION,
                description="Custom Jaan Voice Agent Onboarding & Base Architecture",
                quantity=Decimal("1.00"),
                unit="one-time",
                unit_price=_money(impl_fee),
                amount=_money(impl_fee),
            )
        )

        # Multi-language support
        additional_languages = max(0, inputs.languages_count - 1)
        if additional_languages > 0:
            lang_amount = lang_fee * Decimal(str(additional_languages))
            suggested_items.append(
                SuggestedLineItem(
                    category=QuoteLineItemCategory.IMPLEMENTATION,
                    description=(
                        f"Multi-language Voice Configuration ({additional_languages} additional)"
                    ),
                    quantity=Decimal(str(additional_languages)),
                    unit="language",
                    unit_price=_money(lang_fee),
                    amount=_money(lang_amount),
                )
            )

        # Workflow complexity
        complexity_key = inputs.workflow_complexity.lower()
        complexity_fee = cfg.workflow_complexity_fee.get(complexity_key, Decimal("0.00"))
        if complexity_fee > 0:
            c_label = inputs.workflow_complexity.title()
            suggested_items.append(
                SuggestedLineItem(
                    category=QuoteLineItemCategory.DEVELOPMENT,
                    description=f"Advanced Conversation Workflow ({c_label})",
                    quantity=Decimal("1.00"),
                    unit="one-time",
                    unit_price=_money(complexity_fee),
                    amount=_money(complexity_fee),
                )
            )

        # Integrations
        if inputs.integrations_count > 0:
            int_amount = int_fee * Decimal(str(inputs.integrations_count))
            suggested_items.append(
                SuggestedLineItem(
                    category=QuoteLineItemCategory.INTEGRATIONS,
                    description=f"CRM/API Integrations ({inputs.integrations_count} systems)",
                    quantity=Decimal(str(inputs.integrations_count)),
                    unit="system",
                    unit_price=_money(int_fee),
                    amount=_money(int_amount),
                )
            )

        # Custom tools
        if inputs.custom_tools_count > 0:
            tool_amount = cfg.fee_per_custom_tool * Decimal(str(inputs.custom_tools_count))
            suggested_items.append(
                SuggestedLineItem(
                    category=QuoteLineItemCategory.DEVELOPMENT,
                    description=f"Custom Tools/Actions ({inputs.custom_tools_count} tools)",
                    quantity=Decimal(str(inputs.custom_tools_count)),
                    unit="tool",
                    unit_price=_money(cfg.fee_per_custom_tool),
                    amount=_money(tool_amount),
                )
            )

        # Knowledge Base Setup
        if inputs.knowledge_docs_count > 0:
            suggested_items.append(
                SuggestedLineItem(
                    category=QuoteLineItemCategory.IMPLEMENTATION,
                    description="Company Brain & Knowledge Base Ingestion Pipeline",
                    quantity=Decimal("1.00"),
                    unit="one-time",
                    unit_price=_money(cfg.knowledge_base_setup_fee),
                    amount=_money(cfg.knowledge_base_setup_fee),
                )
            )

        # 3. Recurring items
        # Platform maintenance
        suggested_items.append(
            SuggestedLineItem(
                category=QuoteLineItemCategory.PLATFORM,
                description="Jaan Voice Platform Hosting, Monitoring & Model Maintenance",
                quantity=Decimal("1.00"),
                unit="month",
                unit_price=_money(platform_fee),
                amount=_money(platform_fee),
            )
        )

        # Support tier
        support_key = inputs.support_tier.lower()
        support_fee = cfg.support_tier_monthly_fee.get(support_key, Decimal("0.00"))
        if support_fee > 0:
            suggested_items.append(
                SuggestedLineItem(
                    category=QuoteLineItemCategory.PLATFORM,
                    description=f"SLA & Technical Support ({inputs.support_tier.title()} Tier)",
                    quantity=Decimal("1.00"),
                    unit="month",
                    unit_price=_money(support_fee),
                    amount=_money(support_fee),
                )
            )

        # Dedicated phone numbers
        if inputs.telephony_numbers_count > 0:
            phone_amount = cfg.monthly_fee_per_phone_number * Decimal(
                str(inputs.telephony_numbers_count)
            )
            suggested_items.append(
                SuggestedLineItem(
                    category=QuoteLineItemCategory.PLATFORM,
                    description=f"Telephony Lines ({inputs.telephony_numbers_count} lines)",
                    quantity=Decimal(str(inputs.telephony_numbers_count)),
                    unit="line/mo",
                    unit_price=_money(cfg.monthly_fee_per_phone_number),
                    amount=_money(phone_amount),
                )
            )

        # Voice usage line item (initial starter package)
        voice_credits_estimate = _money(Decimal(str(recommended_included)) * indicative_rate)
        suggested_items.append(
            SuggestedLineItem(
                category=QuoteLineItemCategory.VOICE_CREDITS,
                description=(
                    f"Initial Voice Package ({recommended_included:,} mins @ {indicative_rate}/min)"
                ),
                quantity=Decimal(str(recommended_included)),
                unit="minute",
                unit_price=_money(indicative_rate),
                amount=voice_credits_estimate,
            )
        )

        # Aggregate setup and recurring totals
        total_setup = Decimal("0.00")
        total_recurring = Decimal("0.00")

        for item in suggested_items:
            if item.unit in ("one-time", "language", "system", "tool"):
                total_setup += item.amount
            elif item.unit in ("month", "line/mo"):
                total_recurring += item.amount

        breakdown = {
            "inputs": {
                "monthly_calls": inputs.monthly_calls,
                "avg_call_duration_minutes": float(inputs.avg_call_duration_minutes),
                "languages_count": inputs.languages_count,
                "workflow_complexity": inputs.workflow_complexity,
                "integrations_count": inputs.integrations_count,
                "custom_tools_count": inputs.custom_tools_count,
                "knowledge_docs_count": inputs.knowledge_docs_count,
                "telephony_numbers_count": inputs.telephony_numbers_count,
                "support_tier": inputs.support_tier,
                "currency": inputs.currency,
            },
            "total_monthly_minutes_projected": total_monthly_minutes,
            "recommended_included_minutes": recommended_included,
            "indicative_minute_rate": float(indicative_rate),
            "estimated_setup_fee": float(_money(total_setup)),
            "estimated_recurring_fee": float(_money(total_recurring)),
        }

        return QuoteCalculationEstimate(
            estimated_setup_fee=_money(total_setup),
            estimated_recurring_fee=_money(total_recurring),
            estimated_total_monthly_minutes=total_monthly_minutes,
            recommended_included_minutes=recommended_included,
            indicative_minute_rate=_money(indicative_rate),
            suggested_line_items=suggested_items,
            calculation_breakdown=breakdown,
        )
