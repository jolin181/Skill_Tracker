"""
Interactive Skill Gap Analysis Testing

Run this in Python REPL:
    python -i scripts/test_skill_gap_interactive.py

Then test individual components:
    >>> await test_tools()
    >>> await test_deterministic_analysis()
    >>> await test_full_agent()
"""

import asyncio
from app.core.database import AsyncSessionLocal
from app.modules.ai_engine.skill_gap import (
    SkillGapAgent,
    get_current_assessment_result,
    get_topic_performance,
    get_student_history,
    classify_gap,
    analyze_trend,
    calculate_confidence,
)


async def test_tools():
    """Test individual agent tools."""
    async with AsyncSessionLocal() as db:
        # Find a student and attempt
        from sqlalchemy import select
        from app.modules.attempts.models import Attempt

        query = select(Attempt).where(Attempt.status == 'submitted').limit(1)
        result = await db.execute(query)
        attempt = result.scalar_one_or_none()

        if not attempt:
            print("No attempts found. Create test data first.")
            return

        student_id = attempt.student_id
        attempt_id = attempt.id
        level_id = attempt.level_id

        print(f"Testing with Attempt ID: {attempt_id}")
        print()

        # Test tool 1
        print("Tool 1: get_current_assessment_result")
        current = await get_current_assessment_result(attempt_id, student_id, db)
        print(f"  Result: {current['percentage']:.1f}%")
        print(f"  Topics: {len(current['topic_results'])}")
        print()

        # Test tool 2
        print("Tool 2: get_topic_performance")
        performance = await get_topic_performance(student_id, level_id, db)
        print(f"  Topics: {len(performance)}")
        for p in performance[:3]:
            print(f"    {p['topic_name']}: {p['avg_accuracy']*100:.1f}%")
        print()

        # Test tool 3
        if performance:
            topic_id = performance[0]['topic_id']
            print(f"Tool 3: get_student_history (Topic {topic_id})")
            history = await get_student_history(student_id, topic_id, db)
            print(f"  Attempts: {len(history)}")
            for h in history:
                print(f"    Attempt {h['attempt_no']}: {h['accuracy']*100:.1f}%")
            print()


async def test_deterministic_analysis():
    """Test deterministic analysis functions."""
    print("Testing Deterministic Analysis Functions")
    print("=" * 50)
    print()

    # Test gap classification
    print("1. Gap Classification:")

    # Persistent gap example
    history = [
        {'accuracy': 0.42, 'attempt_no': 1},
        {'accuracy': 0.45, 'attempt_no': 2},
        {'accuracy': 0.44, 'attempt_no': 3},
    ]
    is_gap, classification, persistence = classify_gap(0.44, history, 0.5)
    print(f"   3 attempts at ~44%: {classification} (persistence: {persistence})")

    # Current gap example
    history = [{'accuracy': 0.42, 'attempt_no': 1}]
    is_gap, classification, persistence = classify_gap(0.42, history, 0.5)
    print(f"   1 attempt at 42%: {classification} (persistence: {persistence})")

    # Improving example
    history = [
        {'accuracy': 0.35, 'attempt_no': 1},
        {'accuracy': 0.45, 'attempt_no': 2},
    ]
    is_gap, classification, persistence = classify_gap(0.45, history, 0.5)
    print(f"   35% → 45%: {classification}")
    print()

    # Test trend analysis
    print("2. Trend Analysis:")

    # Improving trend
    history = [
        {'accuracy': 0.40}, {'accuracy': 0.55}, {'accuracy': 0.70}
    ]
    trend, evidence = analyze_trend(history)
    print(f"   40% → 55% → 70%: {trend}")
    print(f"   Evidence: {evidence}")

    # Declining trend
    history = [
        {'accuracy': 0.80}, {'accuracy': 0.60}, {'accuracy': 0.40}
    ]
    trend, evidence = analyze_trend(history)
    print(f"   80% → 60% → 40%: {trend}")
    print(f"   Evidence: {evidence}")
    print()

    # Test confidence calculation
    print("3. Confidence Calculation:")
    conf, factors = calculate_confidence(3, "STABLE", True, True)
    print(f"   3 attempts, stable, full data: {conf}")
    for f in factors:
        print(f"     - {f}")
    print()


async def test_full_agent():
    """Test complete agent workflow."""
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        from app.modules.attempts.models import Attempt

        query = select(Attempt).where(Attempt.status == 'submitted').limit(1)
        result = await db.execute(query)
        attempt = result.scalar_one_or_none()

        if not attempt:
            print("No attempts found.")
            return

        print("Testing Full Agent Workflow")
        print("=" * 50)
        print()

        agent = SkillGapAgent(db)
        analysis = await agent.analyze(
            attempt_id=attempt.id,
            student_id=attempt.student_id,
            llm_available=True
        )

        if analysis.get('success'):
            print("✅ Analysis successful!")
            print()

            det = analysis.get('deterministic_analysis', {})
            print(f"Gaps: {len(det.get('gaps', []))}")
            print(f"Strengths: {len(det.get('strengths', []))}")
            print(f"Confidence: {det.get('confidence')}")
            print()

            if analysis.get('llm_unavailable'):
                print("⚠️  LLM unavailable")
            else:
                print("✅ LLM reasoning completed")
        else:
            print(f"❌ Analysis failed: {analysis.get('error')}")


# Convenience function
def run(coro):
    """Run an async function in the REPL."""
    return asyncio.run(coro)


if __name__ == "__main__":
    print()
    print("Skill Gap Analysis - Interactive Testing")
    print("=" * 50)
    print()
    print("Available functions:")
    print("  run(test_tools())                  - Test agent tools")
    print("  run(test_deterministic_analysis()) - Test analysis functions")
    print("  run(test_full_agent())             - Test complete workflow")
    print()
    print("Example:")
    print('  >>> run(test_tools())')
    print()
