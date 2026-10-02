"""
app/modules/ai_engine/schemas.py
----------------------------------
Pydantic schemas for Skill Gap Analysis Agent.

These schemas define the structured output format for the agent,
ensuring type safety, validation, and consistency.
"""

from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator


class GapItem(BaseModel):
    """Represents a single skill gap identified for a topic."""

    topic_id: int
    topic_name: str
    subtopic_id: Optional[int] = None
    subtopic_name: Optional[str] = None
    accuracy: float = Field(..., ge=0.0, le=1.0, description="Topic accuracy as fraction (0.0-1.0)")
    severity: Literal["HIGH", "MEDIUM", "LOW"] = Field(..., description="Impact severity of this gap")
    priority: int = Field(..., ge=1, description="Priority ranking (1=highest)")
    classification: Literal["PERSISTENT", "CURRENT", "IMPROVING"] = Field(
        ..., description="Gap classification based on historical data"
    )
    trend: Optional[Literal["IMPROVING", "STABLE", "DECLINING", "VOLATILE", "INSUFFICIENT_DATA"]] = None
    evidence: str = Field(..., description="Factual evidence supporting this gap identification")
    reason: str = Field(..., description="Explanation of why this is a gap")
    recommended_action: str = Field(..., description="Specific actionable recommendation")
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = Field(
        ..., description="Confidence level based on data quality"
    )

    @field_validator("accuracy")
    @classmethod
    def validate_accuracy_range(cls, v: float) -> float:
        """Ensure accuracy is between 0.0 and 1.0."""
        if not (0.0 <= v <= 1.0):
            raise ValueError("Accuracy must be between 0.0 and 1.0")
        return v


class StrengthItem(BaseModel):
    """Represents a strong topic area for the student."""

    topic_id: int
    topic_name: str
    accuracy: float = Field(..., ge=0.0, le=1.0, description="Topic accuracy as fraction (0.0-1.0)")
    evidence: str = Field(..., description="Evidence supporting this strength")
    note: Optional[str] = None


class TrendAnalysis(BaseModel):
    """Represents learning trend analysis for a topic."""

    topic_id: int
    topic_name: str
    trend: Literal["IMPROVING", "STABLE", "DECLINING", "VOLATILE", "INSUFFICIENT_DATA"]
    evidence: str = Field(..., description="Historical data supporting the trend")
    interpretation: str = Field(..., description="What this trend means for the student")


class DifficultyInsight(BaseModel):
    """Represents difficulty-specific performance insight."""

    topic_id: int
    topic_name: str
    easy_accuracy: Optional[float] = Field(None, ge=0.0, le=1.0)
    medium_accuracy: Optional[float] = Field(None, ge=0.0, le=1.0)
    hard_accuracy: Optional[float] = Field(None, ge=0.0, le=1.0)
    insight: str = Field(..., description="Interpretation of difficulty pattern")
    recommendation: str = Field(..., description="Specific recommendation based on pattern")


class NextLevelTopic(BaseModel):
    """Represents a topic from the next level curriculum."""

    topic_id: int
    topic_name: str
    description: Optional[str] = None
    requires_preparation: bool = Field(..., description="Whether current gaps affect this topic")
    reason: Optional[str] = Field(None, description="Why preparation is/isn't needed")


class Recommendation(BaseModel):
    """Represents a prioritized learning recommendation."""

    priority: int = Field(..., ge=1, description="Priority ranking (1=highest)")
    topic_id: int
    topic_name: str
    evidence: str = Field(..., description="Evidence supporting this recommendation")
    diagnosis: str = Field(..., description="What the issue is")
    action: str = Field(..., description="Specific action to take")
    practice_direction: Optional[str] = Field(None, description="How to practice")
    next_step: Optional[str] = Field(None, description="Next step after completing action")


class StudyPlanItem(BaseModel):
    """Represents an item in the personalized study plan."""

    order: int = Field(..., ge=1, description="Sequence order in study plan")
    topic_id: int
    topic_name: str
    focus_area: str = Field(..., description="Specific area to focus on")
    time_estimate: Optional[str] = Field(None, description="Estimated time commitment")
    resources: Optional[List[str]] = Field(default_factory=list, description="Recommended resources")
    success_criteria: str = Field(..., description="How to know when this is mastered")


class AdaptiveAssessmentPlan(BaseModel):
    """Represents the adaptive assessment strategy for next exam."""

    target_topics: List[int] = Field(..., description="Topic IDs to prioritize in next assessment")
    recommended_difficulty: Literal["EASY", "MEDIUM", "HARD", "MIXED"] = Field(
        ..., description="Recommended difficulty level"
    )
    focus_areas: List[str] = Field(..., description="Specific areas to focus questions on")
    reason: str = Field(..., description="Why this assessment strategy is recommended")
    avoid_topics: Optional[List[int]] = Field(
        default_factory=list, description="Topics to avoid until gaps are addressed"
    )


class SkillGapAnalysisResponse(BaseModel):
    """
    Complete structured response from the Skill Gap Analysis Agent.

    This represents the full output of the agent after analyzing a student's
    assessment results, combining deterministic calculations with LLM reasoning
    to provide personalized learning guidance.
    """

    # Metadata
    student_id: int
    attempt_id: int
    current_level_id: int
    current_level_name: str
    analysis_version: str = "1.0"
    generated_at: datetime

    # Overall summary
    summary: str = Field(..., description="Concise overall summary of performance and gaps")
    overall_performance: str = Field(
        ..., description="Overall performance assessment for this level"
    )

    # Strengths and gaps
    strengths: List[StrengthItem] = Field(default_factory=list)
    current_gaps: List[GapItem] = Field(
        default_factory=list, description="Gaps identified in current assessment"
    )
    persistent_gaps: List[GapItem] = Field(
        default_factory=list, description="Gaps that have persisted across multiple attempts"
    )

    # Analysis
    trends: List[TrendAnalysis] = Field(
        default_factory=list, description="Learning trend analysis for key topics"
    )
    difficulty_insights: List[DifficultyInsight] = Field(
        default_factory=list, description="Difficulty-specific performance insights"
    )

    # Next level readiness
    next_level_readiness: Literal["READY", "NEEDS_TARGETED_PREPARATION", "SIGNIFICANT_GAPS", "INSUFFICIENT_DATA"]
    next_level_id: Optional[int] = None
    next_level_name: Optional[str] = None
    next_level_topics: List[NextLevelTopic] = Field(
        default_factory=list, description="Topics from next level curriculum"
    )

    # Personalized recommendations
    recommendations: List[Recommendation] = Field(
        ..., description="Prioritized learning recommendations"
    )
    study_plan: List[StudyPlanItem] = Field(
        default_factory=list, description="Structured study plan"
    )

    # Adaptive assessment
    adaptive_assessment_plan: Optional[AdaptiveAssessmentPlan] = Field(
        None, description="Strategy for next assessment"
    )

    # Confidence and evidence
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = Field(
        ..., description="Overall confidence in analysis"
    )
    confidence_factors: List[str] = Field(
        ..., description="Factors affecting confidence level"
    )
    evidence_quality: str = Field(
        ..., description="Assessment of available evidence quality"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "student_id": 123,
                "attempt_id": 456,
                "current_level_id": 2,
                "current_level_name": "Level 2 - Data Structures",
                "analysis_version": "1.0",
                "generated_at": "2024-01-15T10:30:00Z",
                "summary": "Persistent gap in Linked Lists requires targeted practice before progression.",
                "overall_performance": "Mixed performance with strong array handling but weak linked list operations.",
                "strengths": [],
                "current_gaps": [],
                "persistent_gaps": [],
                "trends": [],
                "difficulty_insights": [],
                "next_level_readiness": "NEEDS_TARGETED_PREPARATION",
                "next_level_id": 3,
                "next_level_name": "Level 3 - Advanced Data Structures",
                "next_level_topics": [],
                "recommendations": [],
                "study_plan": [],
                "adaptive_assessment_plan": None,
                "confidence": "HIGH",
                "confidence_factors": ["3 attempts available", "Consistent pattern"],
                "evidence_quality": "High quality with multiple assessment data points"
            }
        }


class SkillGapAnalysisRequest(BaseModel):
    """Request to trigger skill gap analysis."""

    attempt_id: int = Field(..., description="Attempt ID to analyze")
    force_regenerate: bool = Field(
        False, description="Force regeneration even if analysis exists"
    )
