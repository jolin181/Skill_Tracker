"""
Quick demo script to test Skill Gap Analysis Agent

This script demonstrates the agent workflow without requiring
a full frontend setup. It creates test data and triggers analysis.

Usage:
    python scripts/test_skill_gap_demo.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.modules.ai_engine.skill_gap import SkillGapAgent
from app.modules.attempts.models import Attempt, Result, TopicResult
from app.modules.analytics.service import refresh_topic_gap_summary


async def demo_skill_gap_analysis():
    """
    Demonstrate Skill Gap Analysis workflow.

    Prerequisites:
    1. Database migrations applied (alembic upgrade head)
    2. At least one student with completed attempts in the database
    3. Analytics refresh has been run
    """

    print("=" * 60)
    print("SKILL GAP ANALYSIS AGENT - DEMO")
    print("=" * 60)
    print()

    async with AsyncSessionLocal() as db:
        # Step 1: Find a recent attempt with results
        print("Step 1: Finding recent attempt with results...")

        query = (
            select(Attempt, Result)
            .join(Result, Result.attempt_id == Attempt.id)
            .where(Attempt.status == 'submitted')
            .order_by(Attempt.id.desc())
            .limit(1)
        )

        result = await db.execute(query)
        row = result.first()

        if not row:
            print("❌ No completed attempts found in database.")
            print("   Please complete an assessment first.")
            print()
            print("   Quick setup:")
            print("   1. Start the backend: uvicorn app.main:app --reload")
            print("   2. Visit http://localhost:8000/docs")
            print("   3. Create a student and complete an assessment")
            return

        attempt, result_obj = row
        student_id = attempt.student_id
        attempt_id = attempt.id

        print(f"✅ Found Attempt ID: {attempt_id}")
        print(f"   Student ID: {student_id}")
        print(f"   Level ID: {attempt.level_id}")
        print(f"   Score: {result_obj.scored_marks}/{result_obj.total_marks} ({result_obj.percentage:.1f}%)")
        print(f"   Verdict: {result_obj.verdict}")
        print()

        # Step 2: Check if Analytics has data
        print("Step 2: Checking Analytics data...")

        # Refresh topic gap summary for this student
        print("   Refreshing Analytics...")
        await refresh_topic_gap_summary()
        print("   ✅ Analytics refreshed")
        print()

        # Step 3: Load topic results
        print("Step 3: Loading topic performance...")

        topic_results_query = select(TopicResult).where(
            TopicResult.result_id == result_obj.id
        )
        topic_results_result = await db.execute(topic_results_query)
        topic_results = list(topic_results_result.scalars().all())

        print(f"   Found {len(topic_results)} topic results:")
        for tr in topic_results:
            print(f"   - Topic {tr.topic_id}: {tr.accuracy*100:.1f}% ({tr.scored_marks}/{tr.total_marks} marks)")
        print()

        # Step 4: Run Skill Gap Agent
        print("Step 4: Running Skill Gap Agent...")
        print("   Note: This requires LLM_API_KEY in .env for full analysis")
        print()

        agent = SkillGapAgent(db)

        try:
            analysis_result = await agent.analyze(
                attempt_id=attempt_id,
                student_id=student_id,
                llm_available=True
            )

            if not analysis_result.get('success'):
                print(f"❌ Analysis failed: {analysis_result.get('error')}")
                return

            print("✅ Analysis completed!")
            print()

            # Step 5: Display Results
            print("=" * 60)
            print("ANALYSIS RESULTS")
            print("=" * 60)
            print()

            # Check if LLM was available
            if analysis_result.get('llm_unavailable'):
                print("⚠️  LLM unavailable - showing deterministic analysis only")
                print("   (Set LLM_API_KEY in .env for full analysis)")
                print()

            # Display deterministic analysis
            det_analysis = analysis_result.get('deterministic_analysis', {})

            print("CONFIDENCE ASSESSMENT:")
            print(f"  Level: {det_analysis.get('confidence', 'N/A')}")
            factors = det_analysis.get('confidence_factors', [])
            if factors:
                print("  Factors:")
                for factor in factors:
                    print(f"    • {factor}")
            print()

            # Display gaps
            gaps = det_analysis.get('gaps', [])
            if gaps:
                print(f"IDENTIFIED GAPS ({len(gaps)} total):")
                print()

                for gap in gaps[:5]:  # Show top 5
                    print(f"  Priority {gap['priority']}: {gap['topic_name']}")
                    print(f"    Accuracy: {gap['avg_accuracy']*100:.1f}%")
                    print(f"    Classification: {gap['classification']}")
                    print(f"    Severity: {gap['severity']}")
                    if gap.get('trend'):
                        print(f"    Trend: {gap['trend']}")
                    print(f"    Evidence: {gap['evidence']}")
                    print()
            else:
                print("✅ No significant gaps identified!")
                print()

            # Display strengths
            strengths = det_analysis.get('strengths', [])
            if strengths:
                print(f"IDENTIFIED STRENGTHS ({len(strengths)} total):")
                for strength in strengths[:3]:  # Show top 3
                    print(f"  • {strength['topic_name']}: {strength['accuracy']*100:.1f}%")
                print()

            # Display trends
            trends = det_analysis.get('trends', [])
            if trends:
                print(f"LEARNING TRENDS:")
                for trend in trends[:3]:
                    print(f"  • {trend['topic_name']}: {trend['trend']}")
                    print(f"    {trend['evidence']}")
                print()

            # Display LLM interpretation if available
            if 'analysis' in analysis_result and analysis_result['analysis'].get('llm_interpretation'):
                print("=" * 60)
                print("LLM INTERPRETATION:")
                print("=" * 60)
                interpretation = analysis_result['analysis']['llm_interpretation']
                print(interpretation[:500])
                if len(interpretation) > 500:
                    print("...")
                    print(f"[{len(interpretation) - 500} more characters]")
                print()

            print("=" * 60)
            print("NEXT STEPS:")
            print("=" * 60)
            print()
            print("✅ Backend API ready!")
            print()
            print("To view in frontend:")
            print("  1. Start frontend: cd frontend && npm run dev")
            print("  2. Login as student")
            print("  3. Navigate to: Skill Gap Analysis page")
            print()
            print("To test API endpoints:")
            print(f"  GET /api/v1/ai-engine/skill-gap/{attempt_id}")
            print(f"  GET /api/v1/ai-engine/skill-gap/latest")
            print()
            print("To view in Swagger UI:")
            print("  Visit: http://localhost:8000/docs")
            print("  Look for: /api/v1/ai-engine/skill-gap/ endpoints")
            print()

        except Exception as e:
            print(f"❌ Error during analysis: {str(e)}")
            print()
            print("Common issues:")
            print("  • LLM_API_KEY not set in .env")
            print("  • OpenAI API rate limit")
            print("  • Database connection issue")
            print()
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    print()
    print("Starting Skill Gap Analysis Demo...")
    print()

    try:
        asyncio.run(demo_skill_gap_analysis())
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Demo failed: {str(e)}")
        import traceback
        traceback.print_exc()
