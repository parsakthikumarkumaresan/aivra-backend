from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repositories.audit_repository import AuditRepository
from app.audit.services.audit_service import AuditService
from app.organizations.repositories.organization_repository import OrganizationRepository
from app.quotes.models.quote import Quote, QuoteLineItem, QuoteStatus
from app.quotes.repositories.quote_repository import QuoteRepository
from app.quotes.schemas.quote import (
    QuoteCalculationResponse,
    QuoteCalculatorInputSchema,
    QuoteCreateRequest,
    QuoteLineItemResponse,
    QuoteListResponse,
    QuoteResponse,
    QuoteSendRequest,
    QuoteSendResponse,
    QuoteSuggestedLineItemResponse,
    QuoteTransitionRequest,
    QuoteUpdateRequest,
)
from app.quotes.services.quote_calculator_service import (
    QuoteCalculatorInput,
)
from app.quotes.services.quote_service import QuoteService
from app.shared.database.session import get_db
from app.shared.rbac.roles import PlatformRole
from app.shared.security.dependencies import AuthContext, require_platform_role

router = APIRouter(
    prefix="/internal/quotes",
    tags=["Admin — Quotes"],
    dependencies=[
        Depends(require_platform_role(PlatformRole.AIVRA_ADMIN, PlatformRole.AIVRA_ENGINEER))
    ],
)

_INTERNAL_ROLES = (PlatformRole.AIVRA_ADMIN, PlatformRole.AIVRA_ENGINEER)


def _get_service(db: AsyncSession = Depends(get_db)) -> QuoteService:
    quote_repo = QuoteRepository(db)
    org_repo = OrganizationRepository(db)
    audit_repo = AuditRepository(db)
    audit_service = AuditService(audit_repo)
    return QuoteService(
        quote_repo=quote_repo,
        org_repo=org_repo,
        audit_service=audit_service,
    )


def _to_line_item_response(item: QuoteLineItem) -> QuoteLineItemResponse:
    return QuoteLineItemResponse(
        id=item.id,
        category=item.category.value,
        description=item.description,
        quantity=float(item.quantity),
        unit=item.unit,
        unit_price=float(item.unit_price),
        amount=float(item.amount),
        display_order=item.display_order,
    )


def _to_quote_response(quote: Quote) -> QuoteResponse:
    return QuoteResponse(
        id=quote.id,
        organization_id=quote.organization_id,
        lead_id=quote.lead_id,
        voice_project_id=quote.voice_project_id,
        quote_number=quote.quote_number,
        title=quote.title,
        status=quote.status.value,
        currency=quote.currency,
        subtotal=float(quote.subtotal),
        discount=float(quote.discount),
        tax_rate=float(quote.tax_rate),
        tax_amount=float(quote.tax_amount),
        total=float(quote.total),
        valid_until=quote.valid_until,
        notes=quote.notes,
        terms=quote.terms,
        estimated_setup_fee=float(quote.estimated_setup_fee)
        if quote.estimated_setup_fee is not None
        else None,
        estimated_recurring_fee=float(quote.estimated_recurring_fee)
        if quote.estimated_recurring_fee is not None
        else None,
        included_voice_minutes=quote.included_voice_minutes,
        additional_minute_rate=float(quote.additional_minute_rate),
        calculation_snapshot=quote.calculation_snapshot,
        created_by_user_id=quote.created_by_user_id,
        sent_at=quote.sent_at,
        accepted_at=quote.accepted_at,
        rejected_at=quote.rejected_at,
        rejection_reason=quote.rejection_reason,
        created_at=quote.created_at,
        updated_at=quote.updated_at,
        line_items=[_to_line_item_response(i) for i in quote.line_items],
    )


@router.post("/calculate", response_model=QuoteCalculationResponse)
def calculate_quote_estimate(
    payload: QuoteCalculatorInputSchema,
    service: QuoteService = Depends(_get_service),
) -> QuoteCalculationResponse:
    inputs = QuoteCalculatorInput(
        monthly_calls=payload.monthly_calls,
        avg_call_duration_minutes=Decimal(str(payload.avg_call_duration_minutes)),
        languages_count=payload.languages_count,
        workflow_complexity=payload.workflow_complexity,
        integrations_count=payload.integrations_count,
        custom_tools_count=payload.custom_tools_count,
        knowledge_docs_count=payload.knowledge_docs_count,
        telephony_numbers_count=payload.telephony_numbers_count,
        support_tier=payload.support_tier,
        currency=payload.currency,
        target_minute_rate=Decimal(str(payload.target_minute_rate))
        if payload.target_minute_rate is not None
        else None,
        base_implementation_fee=Decimal(str(payload.base_implementation_fee))
        if payload.base_implementation_fee is not None
        else None,
        base_platform_monthly_fee=Decimal(str(payload.base_platform_monthly_fee))
        if payload.base_platform_monthly_fee is not None
        else None,
        fee_per_additional_language=Decimal(str(payload.fee_per_additional_language))
        if payload.fee_per_additional_language is not None
        else None,
        fee_per_integration=Decimal(str(payload.fee_per_integration))
        if payload.fee_per_integration is not None
        else None,
    )
    estimate = service.calculate_estimate(inputs)

    return QuoteCalculationResponse(
        estimated_setup_fee=float(estimate.estimated_setup_fee),
        estimated_recurring_fee=float(estimate.estimated_recurring_fee),
        estimated_total_monthly_minutes=estimate.estimated_total_monthly_minutes,
        recommended_included_minutes=estimate.recommended_included_minutes,
        indicative_minute_rate=float(estimate.indicative_minute_rate),
        suggested_line_items=[
            QuoteSuggestedLineItemResponse(
                category=item.category.value,
                description=item.description,
                quantity=float(item.quantity),
                unit=item.unit,
                unit_price=float(item.unit_price),
                amount=float(item.amount),
            )
            for item in estimate.suggested_line_items
        ],
        calculation_breakdown=estimate.calculation_breakdown,
        disclaimer=estimate.disclaimer,
    )


@router.get("", response_model=QuoteListResponse)
async def list_quotes(
    organization_id: str | None = Query(default=None, alias="organizationId"),
    lead_id: str | None = Query(default=None, alias="leadId"),
    voice_project_id: str | None = Query(default=None, alias="voiceProjectId"),
    status: QuoteStatus | None = Query(default=None),
    search: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    service: QuoteService = Depends(_get_service),
) -> QuoteListResponse:
    quotes, total = await service.quote_repo.search_and_count(
        organization_id=organization_id,
        lead_id=lead_id,
        voice_project_id=voice_project_id,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
    )
    return QuoteListResponse(
        items=[_to_quote_response(q) for q in quotes],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=QuoteResponse, status_code=status.HTTP_201_CREATED)
async def create_quote(
    payload: QuoteCreateRequest,
    auth: AuthContext = Depends(require_platform_role(*_INTERNAL_ROLES)),
    service: QuoteService = Depends(_get_service),
) -> QuoteResponse:
    quote = await service.create_quote(
        organization_id=payload.organization_id,
        title=payload.title,
        valid_until=payload.valid_until,
        currency=payload.currency,
        lead_id=payload.lead_id,
        voice_project_id=payload.voice_project_id,
        notes=payload.notes,
        terms=payload.terms,
        discount=Decimal(str(payload.discount)),
        tax_rate=Decimal(str(payload.tax_rate)),
        included_voice_minutes=payload.included_voice_minutes,
        additional_minute_rate=Decimal(str(payload.additional_minute_rate)),
        estimated_setup_fee=Decimal(str(payload.estimated_setup_fee))
        if payload.estimated_setup_fee is not None
        else None,
        estimated_recurring_fee=Decimal(str(payload.estimated_recurring_fee))
        if payload.estimated_recurring_fee is not None
        else None,
        calculation_snapshot=payload.calculation_snapshot,
        line_items_data=[item.model_dump() for item in payload.line_items],
        created_by_user_id=auth.user.id,
    )
    return _to_quote_response(quote)


@router.get("/{quote_id}", response_model=QuoteResponse)
async def get_quote(
    quote_id: str,
    service: QuoteService = Depends(_get_service),
) -> QuoteResponse:
    quote = await service.get_quote(quote_id)
    return _to_quote_response(quote)


@router.put("/{quote_id}", response_model=QuoteResponse)
async def update_draft_quote(
    quote_id: str,
    payload: QuoteUpdateRequest,
    auth: AuthContext = Depends(require_platform_role(*_INTERNAL_ROLES)),
    service: QuoteService = Depends(_get_service),
) -> QuoteResponse:
    line_items_data = (
        [item.model_dump() for item in payload.line_items]
        if payload.line_items is not None
        else None
    )
    quote = await service.update_draft_quote(
        quote_id=quote_id,
        title=payload.title,
        valid_until=payload.valid_until,
        notes=payload.notes,
        terms=payload.terms,
        discount=Decimal(str(payload.discount)) if payload.discount is not None else None,
        tax_rate=Decimal(str(payload.tax_rate)) if payload.tax_rate is not None else None,
        included_voice_minutes=payload.included_voice_minutes,
        additional_minute_rate=Decimal(str(payload.additional_minute_rate))
        if payload.additional_minute_rate is not None
        else None,
        line_items_data=line_items_data,
        actor_id=auth.user.id,
    )
    return _to_quote_response(quote)


@router.post("/{quote_id}/send", response_model=QuoteSendResponse)
async def send_quote(
    quote_id: str,
    payload: QuoteSendRequest,
    auth: AuthContext = Depends(require_platform_role(*_INTERNAL_ROLES)),
    service: QuoteService = Depends(_get_service),
) -> QuoteSendResponse:
    quote, email_sent, email_error = await service.send_quote(
        quote_id=quote_id,
        recipient_email=payload.recipient_email,
        recipient_name=payload.recipient_name,
        actor_id=auth.user.id,
    )
    return QuoteSendResponse(
        quote=_to_quote_response(quote),
        email_sent=email_sent,
        email_error=email_error,
    )


@router.post("/{quote_id}/transition", response_model=QuoteResponse)
async def transition_quote(
    quote_id: str,
    payload: QuoteTransitionRequest,
    auth: AuthContext = Depends(require_platform_role(*_INTERNAL_ROLES)),
    service: QuoteService = Depends(_get_service),
) -> QuoteResponse:
    target_status = QuoteStatus(payload.target_status)
    quote = await service.transition_status(
        quote_id=quote_id,
        target_status=target_status,
        rejection_reason=payload.rejection_reason,
        actor_id=auth.user.id,
    )
    return _to_quote_response(quote)
