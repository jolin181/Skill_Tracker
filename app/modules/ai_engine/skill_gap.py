"""
app/modules/ai_engine/skill_gap.py
------------------------------------
Skill Gap Analysis Agent - Tools and orchestration.

This module provides:
1. Agent tools for evidence retrieval from Analytics and other modules
2. Deterministic analysis functions (gap detection, trend analysis, confidence)
3. Agentic workflow orchestration combining tools + LLM reasoning

Key principle: Database facts > Deterministic calculations > LLM reasoning
The LLM interprets and explains; it never invents scores, topics, or curriculum.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DIFFICULTY_THRESHOLD_MEDIUM
from app.modules.analytics.models import TopicGapSummary, DifficultyPerformanceSummary
from app.modules.attempts.models import Attempt, Result, TopicResult, AttemptAnswer
from app.modules.domains.models import Topic, Subtopic, Level
from app.modules.progress.models import LevelProgress, Enrollment
from app.modules.ai_engine.models import Question


# ── Agent Tools: Evidence Retrieval ────────────────────────────────────────────


async def get_current_assessment_result(
    attempt_id: int,
    student_id: int,
    db: AsyncSession
) -> Optional[Dict]:
    """
    Tool: Retrieve current assessment result with validation.

    Returns:
        Dict with attempt, result, and topic_results data, or None if not found
    """
    # Load attempt
    attempt_query = select(Attempt).where(
        Attempt.id == attempt_id,
        Attempt.student_id == student_id
    )
    attempt_result = await db.execute(attempt_query)
    attempt = attempt_result.scalar_one_or_none()

    if not attempt:
        return None

    # Load result
    result_query = select(Result).where(Result.attempt_id == attempt_id)
    result_result = await db.execute(result_query)
    result = result_result.scalar_one_or_none()

    if not result:
        return None

    # Load topic results
    topic_results_query = select(TopicResult).where(TopicResult.result_id == result.id)
    topic_results_result = await db.execute(topic_results_query)
    topic_results = list(topic_results_result.scalars().all())

    # Load topic names
    topic_ids = [tr.topic_id for tr in topic_results]
    topics_query = select(Topic).where(Topic.id.in_(topic_ids))
    topics_result = await db.execute(topics_query)
    topics_by_id = {t.id: t for t in topics_result.scalars().all()}

    return {
        "attempt_id": attempt.id,
        "student_id": attempt.student_id,
        "level_id": attempt.level_id,
        "attempt_no": attempt.attempt_no,
        "submitted_at": attempt.submitted_at,
        "total_marks": result.total_marks,
        "scored_marks": result.scored_marks,
        "percentage": result.percentage,
        "verdict": result.verdict,
        "topic_results": [
            {
                "topic_id": tr.topic_id,
                "topic_name": topics_by_id.get(tr.topic_id).name if tr.topic_id in topics_by_id else "Unknown",
                "scored_marks": tr.scored_marks,
                "total_marks": tr.total_marks,
                "accuracy": tr.accuracy,  # 0.0-1.0 fraction
            }
            for tr in topic_results
        ]
    }


async def get_topic_performance(
    student_id: int,
    level_id: int,
    db: AsyncSession
) -> List[Dict]:
    """
    Tool: Retrieve topic performance summary from Analytics.

    Returns:
        List of dicts with topic_id, topic_name, avg_accuracy, attempt_count
    """
    # Get topics for this level
    topics_query = select(Topic).where(Topic.level_id == level_id).order_by(Topic.sequence_no)
    topics_result = await db.execute(topics_query)
    topics = list(topics_result.scalars().all())
    topics_by_id = {t.id: t for t in topics}

    # Get topic gap summary from Analytics
    summary_query = select(TopicGapSummary).where(
        TopicGapSummary.student_id == student_id,
        TopicGapSummary.topic_id.in_(list(topics_by_id.keys()))
    )
    summary_result = await db.execute(summary_query)
    summaries = list(summary_result.scalars().all())

    return [
        {
            "topic_id": s.topic_id,
            "topic_name": topics_by_id.get(s.topic_id).name if s.topic_id in topics_by_id else "Unknown",
            "avg_accuracy": s.avg_accuracy,  # 0.0-1.0 fraction
            "attempt_count": s.attempt_count,
        }
        for s in summaries
    ]


async def get_student_history(
    student_id: int,
    topic_id: int,
    db: AsyncSession
) -> List[Dict]:
    """
    Tool: Retrieve historical performance for a specific topic across all attempts.

    Returns:
        List of dicts ordered by attempt date, with accuracy and attempt info
    """
    # Query: TopicResult -> Result -> Attempt for this student and topic
    query = (
        select(TopicResult, Attempt)
        .join(Result, Result.id == TopicResult.result_id)
        .join(Attempt, Attempt.id == Result.attempt_id)
        .where(
            Attempt.student_id == student_id,
            TopicResult.topic_id == topic_id
        )
        .order_by(Attempt.submitted_at)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "attempt_id": attempt.id,
            "attempt_no": attempt.attempt_no,
            "level_id": attempt.level_id,
            "submitted_at": attempt.submitted_at,
            "accuracy": topic_result.accuracy,  # 0.0-1.0 fraction
            "scored_marks": topic_result.scored_marks,
            "total_marks": topic_result.total_marks,
        }
        for topic_result, attempt in rows
    ]


async def get_difficulty_performance(
    student_id: int,
    topic_id: int,
    db: AsyncSession
) -> Dict[str, float]:
    """
    Tool: Retrieve difficulty-specific performance for a topic.

    Returns:
        Dict mapping difficulty level to accuracy (easy/medium/hard -> float)
    """
    # Query: AttemptAnswer -> Question -> Attempt where question.topic_id matches
    # Calculate accuracy per difficulty level

    query = (
        select(
            Question.difficulty,
            func.count(AttemptAnswer.id).label('total_count'),
            func.sum(
                func.case(
                    (AttemptAnswer.selected_option_id.in_(
                        select(Question.id).where(Question.id == AttemptAnswer.question_id)
                    ), 1),
                    else_=0
                )
            ).label('correct_count')
        )
        .select_from(AttemptAnswer)
        .join(Attempt, Attempt.id == AttemptAnswer.attempt_id)
        .join(Question, Question.id == AttemptAnswer.question_id)
        .where(
            Attempt.student_id == student_id,
            Question.topic_id == topic_id,
            Question.difficulty.isnot(None)
        )
        .group_by(Question.difficulty)
    )

    result = await db.execute(query)
    rows = result.all()

    # Calculate accuracy for each difficulty
    performance = {}
    for row in rows:
        difficulty = row.difficulty.lower() if row.difficulty else "unknown"
        total = row.total_count or 0
        correct = row.correct_count or 0
        accuracy = (correct / total) if total > 0 else 0.0
        performance[difficulty] = accuracy

    return performance


async def get_current_level_syllabus(
    level_id: int,
    db: AsyncSession
) -> Dict:
    """
    Tool: Retrieve current level curriculum from database.

    Returns:
        Dict with level info and list of topics with subtopics
    """
    # Load level
    level_query = select(Level).where(Level.id == level_id)
    level_result = await db.execute(level_query)
    level = level_result.scalar_one_or_none()

    if not level:
        return {"level_id": level_id, "exists": False}

    # Load topics
    topics_query = select(Topic).where(Topic.level_id == level_id).order_by(Topic.sequence_no)
    topics_result = await db.execute(topics_query)
    topics = list(topics_result.scalars().all())

    # Load subtopics
    topic_ids = [t.id for t in topics]
    subtopics_query = select(Subtopic).where(Subtopic.topic_id.in_(topic_ids)).order_by(Subtopic.sequence_no)
    subtopics_result = await db.execute(subtopics_query)
    subtopics = list(subtopics_result.scalars().all())

    # Group subtopics by topic
    subtopics_by_topic = {}
    for st in subtopics:
        if st.topic_id not in subtopics_by_topic:
            subtopics_by_topic[st.topic_id] = []
        subtopics_by_topic[st.topic_id].append({
            "subtopic_id": st.id,
            "name": st.name,
            "description": st.description,
            "sequence_no": st.sequence_no
        })

    return {
        "level_id": level.id,
        "level_name": level.name,
        "level_no": level.level_no,
        "description": level.description,
        "exists": True,
        "topics": [
            {
                "topic_id": t.id,
                "name": t.name,
                "description": t.description,
                "sequence_no": t.sequence_no,
                "is_optional": t.is_optional,
                "subtopics": subtopics_by_topic.get(t.id, [])
            }
            for t in topics
        ]
    }


async def get_next_level_syllabus(
    current_level_id: int,
    student_id: int,
    db: AsyncSession
) -> Optional[Dict]:
    """
    Tool: Retrieve next level curriculum in the student's track.

    Returns:
        Dict with next level info or None if no next level exists
    """
    # Get current level to find track_id
    current_level_query = select(Level).where(Level.id == current_level_id)
    current_level_result = await db.execute(current_level_query)
    current_level = current_level_result.scalar_one_or_none()

    if not current_level:
        return None

    # Get next level (same track, level_no + 1)
    next_level_query = select(Level).where(
        Level.track_id == current_level.track_id,
        Level.level_no == current_level.level_no + 1
    )
    next_level_result = await db.execute(next_level_query)
    next_level = next_level_result.scalar_one_or_none()

    if not next_level:
        return None

    # Use existing function to get syllabus
    return await get_current_level_syllabus(next_level.id, db)


async def get_progression_status(
    student_id: int,
    level_id: int,
    db: AsyncSession
) -> Dict:
    """
    Tool: Retrieve progression status for the student's enrollment.

    Returns:
        Dict with enrollment and level progress status
    """
    # Get level to find track
    level_query = select(Level).where(Level.id == level_id)
    level_result = await db.execute(level_query)
    level = level_result.scalar_one_or_none()

    if not level:
        return {"exists": False}

    # Get enrollment
    enrollment_query = select(Enrollment).where(
        Enrollment.student_id == student_id,
        Enrollment.track_id == level.track_id
    )
    enrollment_result = await db.execute(enrollment_query)
    enrollment = enrollment_result.scalar_one_or_none()

    if not enrollment:
        return {"exists": False, "enrolled": False}

    # Get level progress
    progress_query = select(LevelProgress).where(
        LevelProgress.enrollment_id == enrollment.id,
        LevelProgress.level_id == level_id
    )
    progress_result = await db.execute(progress_query)
    progress = progress_result.scalar_one_or_none()

    return {
        "exists": True,
        "enrolled": True,
        "enrollment_id": enrollment.id,
        "track_id": enrollment.track_id,
        "is_blocked": enrollment.is_blocked,
        "level_progress": {
            "status": progress.status if progress else "not_started",
            "unlocked_at": progress.unlocked_at if progress else None,
            "completed_at": progress.completed_at if progress else None
        } if progress else None
    }


# ── Legacy Functions (used by question generation) ─────────────────────────────


async def get_weak_topics(student_id: int, level_id: int, db: AsyncSession) -> list:
    """
    Return topics with below-threshold accuracy for a student on a level.
    Used to guide AI question generation focus.

    This is the LEGACY function used by question generation.
    """
    performance = await get_topic_performance(student_id, level_id, db)

    # Filter topics below threshold (< 50% is considered weak)
    weak_topics = [
        {
            "topic_id": p["topic_id"],
            "topic_name": p["topic_name"],
            "avg_accuracy": p["avg_accuracy"],
            "attempt_count": p["attempt_count"]
        }
        for p in performance
        if p["avg_accuracy"] < DIFFICULTY_THRESHOLD_MEDIUM
    ]

    return weak_topics


async def get_topic_accuracy_map(student_id: int, level_id: int, db: AsyncSession) -> dict:
    """
    Return a mapping of topic_id → average accuracy for a student on a level.

    This is the LEGACY function used by question generation and difficulty analysis.
    """
    performance = await get_topic_performance(student_id, level_id, db)

    return {
        p["topic_id"]: p["avg_accuracy"]
        for p in performance
    }


# ── Deterministic Analysis Functions ───────────────────────────────────────────


def classify_gap(
    avg_accuracy: float,
    history: List[Dict],
    threshold: float = 0.5
) -> Tuple[bool, str, str]:
    """
    Deterministically classify whether a topic is a gap and its type.

    Args:
        avg_accuracy: Average accuracy across all attempts (0.0-1.0)
        history: List of historical attempts with accuracy
        threshold: Accuracy threshold for identifying gaps

    Returns:
        Tuple of (is_gap, classification, persistence_level)
        - is_gap: True if this is currently a gap
        - classification: "PERSISTENT", "CURRENT", "IMPROVING"
        - persistence_level: "HIGH", "MEDIUM", "LOW"
    """
    is_gap = avg_accuracy < threshold

    if not is_gap:
        return False, "NOT_A_GAP", "NONE"

    # Need at least 2 attempts to determine persistence
    if len(history) < 2:
        return True, "CURRENT", "LOW"

    # Check if all attempts are below threshold (persistent)
    all_below = all(h["accuracy"] < threshold for h in history)

    if all_below:
        if len(history) >= 3:
            return True, "PERSISTENT", "HIGH"
        else:
            return True, "PERSISTENT", "MEDIUM"

    # Check if improving (latest > oldest)
    if len(history) >= 2:
        oldest_accuracy = history[0]["accuracy"]
        latest_accuracy = history[-1]["accuracy"]

        if latest_accuracy > oldest_accuracy + 0.1:  # 10% improvement
            return True, "IMPROVING", "LOW"

    # Default: current gap but not persistent
    return True, "CURRENT", "MEDIUM"


def analyze_trend(history: List[Dict]) -> Tuple[str, str]:
    """
    Deterministically analyze learning trend from historical data.

    Args:
        history: List of historical attempts ordered by date (oldest first)

    Returns:
        Tuple of (trend, evidence)
        trend: "IMPROVING", "STABLE", "DECLINING", "VOLATILE", "INSUFFICIENT_DATA"
        evidence: String description of the data supporting the trend
    """
    if len(history) < 2:
        return "INSUFFICIENT_DATA", "Only one attempt available"

    accuracies = [h["accuracy"] for h in history]

    # Calculate slope (linear trend)
    n = len(accuracies)
    x = list(range(n))
    x_mean = sum(x) / n
    y_mean = sum(accuracies) / n

    numerator = sum((x[i] - x_mean) * (accuracies[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        # All attempts at exactly the same accuracy
        avg_accuracy = sum(accuracies) / n
        evidence = f"Stable at {avg_accuracy*100:.1f}% across {n} attempts"
        return "STABLE", evidence

    slope = numerator / denominator

    # Calculate variance to detect volatility
    variance = sum((acc - y_mean) ** 2 for acc in accuracies) / n
    std_dev = variance ** 0.5

    # High volatility: standard deviation > 0.15 (15%)
    if std_dev > 0.15:
        evidence = f"Volatile: scores range from {min(accuracies)*100:.1f}% to {max(accuracies)*100:.1f}%"
        return "VOLATILE", evidence

    # Determine trend based on slope
    if slope > 0.05:  # Improving: >5% per attempt
        evidence = f"Improving: from {accuracies[0]*100:.1f}% to {accuracies[-1]*100:.1f}% over {n} attempts"
        return "IMPROVING", evidence
    elif slope < -0.05:  # Declining: <-5% per attempt
        evidence = f"Declining: from {accuracies[0]*100:.1f}% to {accuracies[-1]*100:.1f}% over {n} attempts"
        return "DECLINING", evidence
    else:  # Stable: between -5% and +5%
        evidence = f"Stable around {y_mean*100:.1f}% over {n} attempts"
        return "STABLE", evidence


def calculate_confidence(
    attempt_count: int,
    trend: str,
    has_difficulty_data: bool,
    has_next_level_data: bool
) -> Tuple[str, List[str]]:
    """
    Deterministically calculate confidence level for the analysis.

    Args:
        attempt_count: Number of attempts available
        trend: Trend classification from analyze_trend
        has_difficulty_data: Whether difficulty-specific data is available
        has_next_level_data: Whether next level curriculum data is available

    Returns:
        Tuple of (confidence_level, factors)
        confidence_level: "HIGH", "MEDIUM", "LOW"
        factors: List of strings explaining confidence factors
    """
    factors = []
    score = 0

    # Attempt count is the primary factor
    if attempt_count >= 3:
        score += 3
        factors.append(f"{attempt_count} attempts available")
    elif attempt_count == 2:
        score += 2
        factors.append(f"{attempt_count} attempts available")
    else:
        score += 1
        factors.append(f"Only {attempt_count} attempt available")

    # Trend consistency
    if trend in ["IMPROVING", "DECLINING", "PERSISTENT"]:
        score += 1
        factors.append("Consistent performance pattern")
    elif trend == "VOLATILE":
        score -= 1
        factors.append("Volatile performance pattern reduces confidence")
    elif trend == "INSUFFICIENT_DATA":
        factors.append("Limited historical data")

    # Additional data availability
    if has_difficulty_data:
        score += 1
        factors.append("Difficulty-specific performance data available")

    if has_next_level_data:
        score += 1
        factors.append("Next level curriculum data available")

    # Determine confidence level
    if score >= 5:
        return "HIGH", factors
    elif score >= 3:
        return "MEDIUM", factors
    else:
        return "LOW", factors


def calculate_severity(
    avg_accuracy: float,
    classification: str,
    is_optional: bool = False
) -> str:
    """
    Deterministically calculate gap severity.

    Args:
        avg_accuracy: Average accuracy (0.0-1.0)
        classification: Gap classification ("PERSISTENT", "CURRENT", "IMPROVING")
        is_optional: Whether this topic is optional in curriculum

    Returns:
        "HIGH", "MEDIUM", or "LOW"
    """
    if is_optional:
        # Optional topics are always lower severity
        if avg_accuracy < 0.3:
            return "MEDIUM"
        else:
            return "LOW"

    # For core topics
    if classification == "PERSISTENT":
        if avg_accuracy < 0.3:
            return "HIGH"
        elif avg_accuracy < 0.5:
            return "HIGH"
        else:
            return "MEDIUM"
    elif classification == "CURRENT":
        if avg_accuracy < 0.3:
            return "HIGH"
        elif avg_accuracy < 0.5:
            return "MEDIUM"
        else:
            return "LOW"
    else:  # IMPROVING
        if avg_accuracy < 0.3:
            return "MEDIUM"
        else:
            return "LOW"


def prioritize_gaps(gaps: List[Dict]) -> List[Dict]:
    """
    Deterministically prioritize gaps for recommendations.

    Args:
        gaps: List of gap dicts with severity, classification, avg_accuracy

    Returns:
        Same list sorted by priority (highest priority first)
    """
    # Priority rules:
    # 1. HIGH severity before MEDIUM before LOW
    # 2. Within same severity, PERSISTENT before CURRENT before IMPROVING
    # 3. Within same severity+classification, lower accuracy first

    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    classification_order = {"PERSISTENT": 0, "CURRENT": 1, "IMPROVING": 2}

    def priority_key(gap: Dict) -> Tuple:
        return (
            severity_order.get(gap.get("severity", "LOW"), 2),
            classification_order.get(gap.get("classification", "CURRENT"), 1),
            gap.get("avg_accuracy", 1.0)  # Lower accuracy = higher priority
        )

    sorted_gaps = sorted(gaps, key=priority_key)

    # Add priority ranking
    for idx, gap in enumerate(sorted_gaps):
        gap["priority"] = idx + 1

    return sorted_gaps


def analyze_difficulty_pattern(difficulty_performance: Dict[str, float]) -> Tuple[Optional[str], Optional[str]]:
    """
    Deterministically analyze difficulty-specific performance pattern.

    Args:
        difficulty_performance: Dict mapping difficulty to accuracy

    Returns:
        Tuple of (insight, recommendation) or (None, None) if insufficient data
    """
    if not difficulty_performance:
        return None, None

    easy = difficulty_performance.get("easy")
    medium = difficulty_performance.get("medium")
    hard = difficulty_performance.get("hard")

    # Need at least 2 difficulty levels to identify a pattern
    available = sum([easy is not None, medium is not None, hard is not None])
    if available < 2:
        return None, None

    # Pattern 1: Stronger on easy, weaker on hard (expected)
    if easy and hard and easy > 0.7 and hard < 0.3:
        insight = f"Strong on easy questions ({easy*100:.0f}%) but weak on hard ({hard*100:.0f}%)"
        recommendation = "Progress from medium-level practice toward harder problems"
        return insight, recommendation

    # Pattern 2: Consistently low across all difficulties
    accuracies = [v for v in [easy, medium, hard] if v is not None]
    if all(acc < 0.4 for acc in accuracies):
        avg = sum(accuracies) / len(accuracies)
        insight = f"Consistently low performance across all difficulty levels ({avg*100:.0f}% average)"
        recommendation = "Start with foundational concepts before attempting harder problems"
        return insight, recommendation

    # Pattern 3: Consistently high across all difficulties
    if all(acc > 0.7 for acc in accuracies):
        avg = sum(accuracies) / len(accuracies)
        insight = f"Strong performance across all difficulty levels ({avg*100:.0f}% average)"
        recommendation = "Ready to progress to more advanced topics"
        return insight, recommendation

    # Pattern 4: Volatile/inconsistent across difficulties
    if len(accuracies) >= 2:
        variance = sum((acc - sum(accuracies)/len(accuracies))**2 for acc in accuracies) / len(accuracies)
        if variance > 0.1:  # High variance
            insight = "Inconsistent performance across difficulty levels"
            recommendation = "Focus on building consistent understanding at all levels"
            return insight, recommendation

    return None, None


# ── Agentic Workflow Orchestration ─────────────────────────────────────────────


class SkillGapAgent:
    """
    Agentic workflow for Skill Gap Analysis.

    Orchestrates:
    1. Evidence retrieval via tools
    2. Deterministic analysis
    3. LLM reasoning with grounded prompt
    4. Structured output validation
    5. Error handling

    The agent NEVER invents data - it combines database facts with LLM interpretation.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def analyze(
        self,
        attempt_id: int,
        student_id: int,
        llm_available: bool = True
    ) -> Dict:
        """
        Perform complete skill gap analysis for an attempt.

        Args:
            attempt_id: Attempt ID to analyze
            student_id: Student ID (for authorization)
            llm_available: Whether LLM is available for reasoning

        Returns:
            Dict with complete analysis or error information

        Raises:
            Does not raise - returns error information in dict if analysis fails
        """
        from app.modules.ai_engine.llm_client import llm_client
        from app.modules.ai_engine.prompts.skill_gap_agent import build_skill_gap_prompt
        from app.modules.ai_engine.schemas import SkillGapAnalysisResponse

        try:
            # Step 1: Retrieve current assessment result
            current_result = await get_current_assessment_result(attempt_id, student_id, self.db)
            if not current_result:
                return {
                    "success": False,
                    "error": "Assessment result not found or access denied"
                }

            level_id = current_result['level_id']

            # Step 2: Retrieve topic performance from Analytics
            topic_performance = await get_topic_performance(student_id, level_id, self.db)

            # Step 3: Retrieve historical performance for each topic
            student_history = {}
            for tp in topic_performance:
                topic_id = tp['topic_id']
                history = await get_student_history(student_id, topic_id, self.db)
                if history:
                    student_history[topic_id] = history

            # Step 4: Retrieve difficulty-specific performance
            difficulty_performance = {}
            for tp in topic_performance:
                topic_id = tp['topic_id']
                diff_perf = await get_difficulty_performance(student_id, topic_id, self.db)
                if diff_perf:
                    difficulty_performance[topic_id] = diff_perf

            # Step 5: Retrieve current level syllabus
            current_syllabus = await get_current_level_syllabus(level_id, self.db)
            if not current_syllabus.get('exists'):
                return {
                    "success": False,
                    "error": "Current level syllabus not found"
                }

            # Step 6: Retrieve next level syllabus
            next_syllabus = await get_next_level_syllabus(level_id, student_id, self.db)

            # Step 7: Retrieve progression status
            progression_status = await get_progression_status(student_id, level_id, self.db)

            # Step 8: Perform deterministic analysis
            deterministic_analysis = self._perform_deterministic_analysis(
                topic_performance,
                student_history,
                difficulty_performance,
                current_syllabus,
                next_syllabus
            )

            # Step 9: If LLM unavailable, return deterministic analysis only
            if not llm_available or not llm_client.client:
                return {
                    "success": True,
                    "llm_unavailable": True,
                    "deterministic_analysis": deterministic_analysis,
                    "current_result": current_result,
                    "message": "LLM unavailable - returning deterministic analysis only"
                }

            # Step 10: Build grounded prompt
            prompt = build_skill_gap_prompt(
                student_id=student_id,
                current_result=current_result,
                topic_performance=topic_performance,
                student_history=student_history,
                difficulty_performance=difficulty_performance,
                current_syllabus=current_syllabus,
                next_syllabus=next_syllabus,
                progression_status=progression_status,
                deterministic_analysis=deterministic_analysis
            )

            # Step 11: Call LLM with structured output
            try:
                # Use generate_structured for Pydantic validation
                # Note: We'll build the response manually due to complexity
                llm_response = await llm_client.generate(
                    prompt=prompt,
                    max_tokens=4000,
                    temperature=0.3
                )

                # Step 12: Parse and validate LLM response
                analysis_response = self._build_structured_response(
                    llm_response,
                    student_id,
                    attempt_id,
                    current_result,
                    current_syllabus,
                    next_syllabus,
                    deterministic_analysis
                )

                return {
                    "success": True,
                    "analysis": analysis_response,
                    "deterministic_analysis": deterministic_analysis
                }

            except Exception as llm_error:
                # LLM failed but assessment must still work
                return {
                    "success": True,
                    "llm_error": str(llm_error),
                    "deterministic_analysis": deterministic_analysis,
                    "current_result": current_result,
                    "message": "LLM reasoning failed - returning deterministic analysis"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Analysis failed: {str(e)}"
            }

    def _perform_deterministic_analysis(
        self,
        topic_performance: List[Dict],
        student_history: Dict[int, List[Dict]],
        difficulty_performance: Dict[int, Dict[str, float]],
        current_syllabus: Dict,
        next_syllabus: Optional[Dict]
    ) -> Dict:
        """
        Perform all deterministic analysis (no LLM involved).

        Returns:
            Dict with gaps, strengths, trends, confidence, etc.
        """
        gaps = []
        strengths = []
        trends = []
        diff_insights = []

        # Build topics lookup
        topics_by_id = {
            t['topic_id']: t
            for t in current_syllabus.get('topics', [])
        }

        for tp in topic_performance:
            topic_id = tp['topic_id']
            topic_name = tp['topic_name']
            avg_accuracy = tp['avg_accuracy']
            attempt_count = tp['attempt_count']

            # Get history for this topic
            history = student_history.get(topic_id, [])

            # Classify gap
            is_gap, classification, persistence_level = classify_gap(
                avg_accuracy,
                history,
                threshold=DIFFICULTY_THRESHOLD_MEDIUM
            )

            # Analyze trend
            trend, trend_evidence = analyze_trend(history)

            if is_gap:
                # Determine if topic is optional
                topic_info = topics_by_id.get(topic_id, {})
                is_optional = topic_info.get('is_optional', False)

                # Calculate severity
                severity = calculate_severity(avg_accuracy, classification, is_optional)

                # Build evidence string
                evidence = f"{avg_accuracy*100:.1f}% average across {attempt_count} attempts"
                if len(history) > 1:
                    evidence += f". {trend_evidence}"

                gaps.append({
                    "topic_id": topic_id,
                    "topic_name": topic_name,
                    "avg_accuracy": avg_accuracy,
                    "classification": classification,
                    "trend": trend,
                    "severity": severity,
                    "persistence_level": persistence_level,
                    "evidence": evidence,
                    "attempt_count": attempt_count
                })
            else:
                # Strong topic (strength)
                strengths.append({
                    "topic_id": topic_id,
                    "topic_name": topic_name,
                    "accuracy": avg_accuracy,
                    "evidence": f"{avg_accuracy*100:.1f}% average across {attempt_count} attempts"
                })

            # Record trend for all topics with sufficient data
            if trend != "INSUFFICIENT_DATA":
                trends.append({
                    "topic_id": topic_id,
                    "topic_name": topic_name,
                    "trend": trend,
                    "evidence": trend_evidence
                })

            # Analyze difficulty patterns
            if topic_id in difficulty_performance:
                diff_perf = difficulty_performance[topic_id]
                insight, recommendation = analyze_difficulty_pattern(diff_perf)
                if insight:
                    diff_insights.append({
                        "topic_id": topic_id,
                        "topic_name": topic_name,
                        "difficulty_performance": diff_perf,
                        "insight": insight,
                        "recommendation": recommendation
                    })

        # Prioritize gaps
        gaps = prioritize_gaps(gaps)

        # Calculate overall confidence
        has_difficulty_data = len(difficulty_performance) > 0
        has_next_level_data = next_syllabus is not None and next_syllabus.get('exists', False)
        avg_attempt_count = sum(tp['attempt_count'] for tp in topic_performance) / len(topic_performance) if topic_performance else 0

        confidence, confidence_factors = calculate_confidence(
            int(avg_attempt_count),
            trends[0]['trend'] if trends else "INSUFFICIENT_DATA",
            has_difficulty_data,
            has_next_level_data
        )

        return {
            "gaps": gaps,
            "strengths": strengths,
            "trends": trends,
            "difficulty_insights": diff_insights,
            "confidence": confidence,
            "confidence_factors": confidence_factors
        }

    def _build_structured_response(
        self,
        llm_response: str,
        student_id: int,
        attempt_id: int,
        current_result: Dict,
        current_syllabus: Dict,
        next_syllabus: Optional[Dict],
        deterministic_analysis: Dict
    ) -> Dict:
        """
        Build structured response combining LLM output with deterministic data.

        For now, returns a simplified structure. In production, would parse LLM
        output into proper SkillGapAnalysisResponse schema.

        Args:
            llm_response: Raw LLM text output
            student_id: Student ID
            attempt_id: Attempt ID
            current_result: Current assessment result
            current_syllabus: Current level curriculum
            next_syllabus: Next level curriculum (optional)
            deterministic_analysis: Pre-computed analysis

        Returns:
            Dict with structured analysis
        """
        # Build structured response from deterministic analysis and LLM interpretation
        return {
            "student_id": student_id,
            "attempt_id": attempt_id,
            "current_level_id": current_syllabus['level_id'],
            "current_level_name": current_syllabus['level_name'],
            "analysis_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),

            # LLM interpretation
            "llm_interpretation": llm_response,

            # Deterministic facts
            "overall_performance": {
                "percentage": current_result['percentage'],
                "verdict": current_result['verdict'],
                "scored_marks": current_result['scored_marks'],
                "total_marks": current_result['total_marks']
            },

            "strengths": deterministic_analysis['strengths'],
            "gaps": deterministic_analysis['gaps'],
            "trends": deterministic_analysis['trends'],
            "difficulty_insights": deterministic_analysis['difficulty_insights'],

            "next_level": {
                "exists": next_syllabus is not None and next_syllabus.get('exists', False),
                "level_id": next_syllabus.get('level_id') if next_syllabus else None,
                "level_name": next_syllabus.get('level_name') if next_syllabus else None
            },

            "confidence": deterministic_analysis['confidence'],
            "confidence_factors": deterministic_analysis['confidence_factors']
        }
