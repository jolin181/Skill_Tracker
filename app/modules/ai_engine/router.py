"""
app/modules/ai_engine/router.py
---------------------------------
AI engine module router.

Endpoints:
- Skill Gap Analysis (student-facing)
- Question generation (admin-only - TODO)
- Question management (admin-only - TODO)
"""

from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import NotFoundError, ForbiddenError
from app.modules.ai_engine.models import SkillGapReport, SkillGapItem
from app.modules.ai_engine.schemas import SkillGapAnalysisRequest
from app.modules.ai_engine.skill_gap import SkillGapAgent
from app.modules.attempts.models import Attempt

router = APIRouter()


@router.get("/", summary="AI engine module health check")
async def ai_engine_root() -> dict:
    """Placeholder endpoint — confirms the ai_engine module is mounted."""
    return {"module": "ai-engine", "status": "ok"}


@router.post("/skill-gap/analyze", summary="Trigger skill gap analysis for an attempt")
async def analyze_skill_gap(
    request: SkillGapAnalysisRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Trigger skill gap analysis for a specific attempt.

    Authorization: Student can only analyze their own attempts.
    Admins can analyze any attempt.

    Returns the complete analysis or uses cached analysis if available
    (unless force_regenerate=True).
    """
    # Load attempt to verify ownership
    attempt_query = select(Attempt).where(Attempt.id == request.attempt_id)
    attempt_result = await db.execute(attempt_query)
    attempt = attempt_result.scalar_one_or_none()

    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attempt {request.attempt_id} not found"
        )

    # Authorization: student can only analyze their own attempts
    if current_user['role'] == 'student':
        if attempt.student_id != current_user['id']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        student_id = current_user['id']
    else:
        # Admin can analyze any attempt
        student_id = attempt.student_id

    # Check if analysis already exists (unless force regenerate)
    if not request.force_regenerate:
        existing_query = select(SkillGapReport).where(
            SkillGapReport.attempt_id == request.attempt_id
        )
        existing_result = await db.execute(existing_query)
        existing = existing_result.scalar_one_or_none()

        if existing:
            # Return existing analysis
            items_query = select(SkillGapItem).where(
                SkillGapItem.report_id == existing.id
            ).order_by(SkillGapItem.priority)
            items_result = await db.execute(items_query)
            items = list(items_result.scalars().all())

            return {
                "success": True,
                "cached": True,
                "report": _serialize_report(existing, items)
            }

    # Run agent analysis
    agent = SkillGapAgent(db)
    analysis_result = await agent.analyze(request.attempt_id, student_id, llm_available=True)

    if not analysis_result.get('success'):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=analysis_result.get('error', 'Analysis failed')
        )

    # Persist analysis to database
    report = await _persist_analysis(
        attempt_id=request.attempt_id,
        student_id=student_id,
        level_id=attempt.level_id,
        analysis_result=analysis_result,
        db=db
    )

    # Load items
    items_query = select(SkillGapItem).where(
        SkillGapItem.report_id == report.id
    ).order_by(SkillGapItem.priority)
    items_result = await db.execute(items_query)
    items = list(items_result.scalars().all())

    return {
        "success": True,
        "cached": False,
        "llm_available": not analysis_result.get('llm_unavailable', False),
        "report": _serialize_report(report, items)
    }


@router.get("/skill-gap/latest", summary="Get latest skill gap analysis for current student")
async def get_latest_skill_gap(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Get the most recent skill gap analysis for the authenticated student.

    Authorization: Students get their own latest analysis.
    Admins must use GET /skill-gap/{attempt_id} with a specific attempt.
    """
    if current_user['role'] != 'student':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins must specify an attempt_id"
        )

    student_id = current_user['id']

    # Get latest report for this student
    report_query = (
        select(SkillGapReport)
        .where(SkillGapReport.student_id == student_id)
        .order_by(desc(SkillGapReport.created_at))
        .limit(1)
    )
    report_result = await db.execute(report_query)
    report = report_result.scalar_one_or_none()

    if not report:
        return {
            "success": True,
            "exists": False,
            "message": "No skill gap analysis available. Complete an assessment first."
        }

    # Load gap items
    items_query = select(SkillGapItem).where(
        SkillGapItem.report_id == report.id
    ).order_by(SkillGapItem.priority)
    items_result = await db.execute(items_query)
    items = list(items_result.scalars().all())

    return {
        "success": True,
        "exists": True,
        "report": _serialize_report(report, items)
    }


@router.get("/skill-gap/{attempt_id}", summary="Get skill gap analysis for specific attempt")
async def get_skill_gap_by_attempt(
    attempt_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Get skill gap analysis for a specific attempt.

    Authorization: Students can only access their own attempts.
    Admins can access any attempt.
    """
    # Load attempt to verify ownership
    attempt_query = select(Attempt).where(Attempt.id == attempt_id)
    attempt_result = await db.execute(attempt_query)
    attempt = attempt_result.scalar_one_or_none()

    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attempt {attempt_id} not found"
        )

    # Authorization check
    if current_user['role'] == 'student' and attempt.student_id != current_user['id']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    # Load report
    report_query = select(SkillGapReport).where(
        SkillGapReport.attempt_id == attempt_id
    )
    report_result = await db.execute(report_query)
    report = report_result.scalar_one_or_none()

    if not report:
        return {
            "success": True,
            "exists": False,
            "message": f"No skill gap analysis for attempt {attempt_id}. Trigger analysis first."
        }

    # Load gap items
    items_query = select(SkillGapItem).where(
        SkillGapItem.report_id == report.id
    ).order_by(SkillGapItem.priority)
    items_result = await db.execute(items_query)
    items = list(items_result.scalars().all())

    return {
        "success": True,
        "exists": True,
        "report": _serialize_report(report, items)
    }


# ── Helper Functions ────────────────────────────────────────────────────────────


async def _persist_analysis(
    attempt_id: int,
    student_id: int,
    level_id: int,
    analysis_result: dict,
    db: AsyncSession
) -> SkillGapReport:
    """
    Persist analysis result to database.

    Handles both full LLM analysis and deterministic-only analysis.
    Uses upsert pattern (delete existing + insert new).
    """
    # Delete existing report if any
    existing_query = select(SkillGapReport).where(
        SkillGapReport.attempt_id == attempt_id
    )
    existing_result = await db.execute(existing_query)
    existing = existing_result.scalar_one_or_none()

    if existing:
        # Delete existing items
        await db.execute(
            select(SkillGapItem).where(SkillGapItem.report_id == existing.id)
        )
        items_to_delete = await db.execute(
            select(SkillGapItem).where(SkillGapItem.report_id == existing.id)
        )
        for item in items_to_delete.scalars():
            await db.delete(item)
        await db.delete(existing)
        await db.flush()

    # Extract analysis data
    if 'analysis' in analysis_result:
        analysis = analysis_result['analysis']
    else:
        # Deterministic only
        analysis = analysis_result.get('deterministic_analysis', {})

    # Create report
    report = SkillGapReport(
        student_id=student_id,
        attempt_id=attempt_id,
        level_id=level_id,
        created_at=datetime.now(timezone.utc),
        summary=analysis.get('llm_interpretation', '')[:500] if 'llm_interpretation' in analysis else "Deterministic analysis only",
        overall_performance=str(analysis.get('overall_performance', {})),
        recommendations=analysis.get('recommendations', []),
        study_plan=analysis.get('study_plan', []),
        next_level_readiness=analysis.get('next_level_readiness', 'INSUFFICIENT_DATA'),
        next_level_id=analysis.get('next_level', {}).get('level_id'),
        adaptive_assessment_plan=analysis.get('adaptive_assessment_plan'),
        confidence=analysis.get('confidence', 'LOW'),
        confidence_factors=analysis.get('confidence_factors', []),
        evidence_quality="See analysis details",
        analysis_version="1.0",
        llm_interpretation=analysis.get('llm_interpretation')
    )
    db.add(report)
    await db.flush()

    # Create gap items
    det_analysis = analysis_result.get('deterministic_analysis', {})
    for gap in det_analysis.get('gaps', []):
        item = SkillGapItem(
            report_id=report.id,
            topic_id=gap['topic_id'],
            topic_name=gap['topic_name'],
            accuracy=gap['avg_accuracy'],
            severity=gap['severity'],
            priority=gap['priority'],
            classification=gap['classification'],
            trend=gap.get('trend'),
            evidence=gap['evidence'],
            reason=f"{gap['classification']} gap",
            recommended_action="See recommendations",
            confidence=det_analysis.get('confidence', 'LOW')
        )
        db.add(item)

    await db.commit()
    await db.refresh(report)

    return report


def _serialize_report(report: SkillGapReport, items: list[SkillGapItem]) -> dict:
    """Serialize report and items to dict for API response."""
    return {
        "id": report.id,
        "student_id": report.student_id,
        "attempt_id": report.attempt_id,
        "level_id": report.level_id,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "summary": report.summary,
        "overall_performance": report.overall_performance,
        "recommendations": report.recommendations,
        "study_plan": report.study_plan,
        "next_level_readiness": report.next_level_readiness,
        "next_level_id": report.next_level_id,
        "adaptive_assessment_plan": report.adaptive_assessment_plan,
        "confidence": report.confidence,
        "confidence_factors": report.confidence_factors,
        "evidence_quality": report.evidence_quality,
        "analysis_version": report.analysis_version,
        "llm_interpretation": report.llm_interpretation,
        "gaps": [
            {
                "id": item.id,
                "topic_id": item.topic_id,
                "topic_name": item.topic_name,
                "subtopic_id": item.subtopic_id,
                "subtopic_name": item.subtopic_name,
                "accuracy": item.accuracy,
                "severity": item.severity,
                "priority": item.priority,
                "classification": item.classification,
                "trend": item.trend,
                "evidence": item.evidence,
                "reason": item.reason,
                "recommended_action": item.recommended_action,
                "confidence": item.confidence
            }
            for item in items
        ]
    }
