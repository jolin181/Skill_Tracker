"""
app/modules/ai_engine/prompts/skill_gap_agent.py
--------------------------------------------------
Grounding prompt for the Skill Gap Analysis Agent.

This prompt instructs the LLM to interpret evidence and generate personalized
learning recommendations WITHOUT inventing facts, scores, or curriculum.
"""

from typing import Dict, List


def build_skill_gap_prompt(
    student_id: int,
    current_result: Dict,
    topic_performance: List[Dict],
    student_history: Dict[int, List[Dict]],
    difficulty_performance: Dict[int, Dict[str, float]],
    current_syllabus: Dict,
    next_syllabus: Dict | None,
    progression_status: Dict,
    deterministic_analysis: Dict
) -> str:
    """
    Build the complete prompt for the Skill Gap Analysis Agent.

    Args:
        student_id: Student ID
        current_result: Current assessment result data
        topic_performance: Topic performance summary from Analytics
        student_history: Historical performance by topic_id
        difficulty_performance: Difficulty-specific performance by topic_id
        current_syllabus: Current level curriculum
        next_syllabus: Next level curriculum (or None)
        progression_status: Enrollment and progression data
        deterministic_analysis: Pre-computed gaps, trends, confidence, etc.

    Returns:
        Complete prompt string for the LLM
    """

    prompt = f"""You are a Personalized Learning Decision Agent analyzing a student's assessment results.

Your role is to interpret factual evidence and generate personalized, actionable learning recommendations.

CRITICAL RULES:
1. Use ONLY the supplied evidence below. Never invent scores, topics, curriculum, or history.
2. Never calculate scores yourself - all numerical analysis is already computed.
3. Distinguish between measured data (what was tested) and recommendations (what should be learned).
4. Distinguish between current weakness (single bad result) and persistent weakness (consistent pattern).
5. If evidence is insufficient, explicitly state "Insufficient evidence" rather than guessing.
6. Keep recommendations concise, specific, and actionable.
7. Prioritize recommendations based on the supplied priority rankings.
8. Use actual curriculum topics provided - do not invent topics or prerequisites.

# SUPPLIED EVIDENCE

## Current Assessment Result
Student ID: {student_id}
Attempt ID: {current_result['attempt_id']}
Level: {current_syllabus['level_name']} (Level {current_syllabus['level_no']})
Attempt Number: {current_result['attempt_no']}
Overall Score: {current_result['scored_marks']}/{current_result['total_marks']} ({current_result['percentage']:.1f}%)
Verdict: {current_result['verdict']}
Submitted: {current_result['submitted_at']}

### Topic Results (Current Assessment)
"""

    for tr in current_result['topic_results']:
        prompt += f"- {tr['topic_name']}: {tr['scored_marks']}/{tr['total_marks']} ({tr['accuracy']*100:.1f}%)\n"

    prompt += "\n## Topic Performance Summary (from Analytics)\n"
    for tp in topic_performance:
        prompt += f"- {tp['topic_name']}: {tp['avg_accuracy']*100:.1f}% average across {tp['attempt_count']} attempts\n"

    prompt += "\n## Historical Performance by Topic\n"
    if student_history:
        for topic_id, history in student_history.items():
            if history:
                topic_name = history[0].get('topic_name', f'Topic {topic_id}')
                prompt += f"\n### {topic_name}\n"
                for h in history:
                    prompt += f"  - Attempt {h['attempt_no']} ({h['submitted_at']}): {h['accuracy']*100:.1f}%\n"
    else:
        prompt += "No historical data available beyond current assessment.\n"

    prompt += "\n## Difficulty-Specific Performance\n"
    if difficulty_performance:
        for topic_id, diff_perf in difficulty_performance.items():
            topic_name = next((t['topic_name'] for t in topic_performance if t['topic_id'] == topic_id), f'Topic {topic_id}')
            prompt += f"\n### {topic_name}\n"
            for difficulty, accuracy in diff_perf.items():
                prompt += f"  - {difficulty.capitalize()}: {accuracy*100:.1f}%\n"
    else:
        prompt += "No difficulty-specific data available.\n"

    prompt += f"\n## Current Level Curriculum\n"
    prompt += f"Level: {current_syllabus['level_name']} (Level {current_syllabus['level_no']})\n"
    prompt += f"Description: {current_syllabus.get('description', 'N/A')}\n"
    prompt += "\nTopics:\n"
    for topic in current_syllabus.get('topics', []):
        optional_marker = " (Optional)" if topic.get('is_optional') else ""
        prompt += f"- {topic['name']}{optional_marker}\n"
        if topic.get('subtopics'):
            for subtopic in topic['subtopics']:
                prompt += f"  - {subtopic['name']}\n"

    if next_syllabus and next_syllabus.get('exists'):
        prompt += f"\n## Next Level Curriculum\n"
        prompt += f"Level: {next_syllabus['level_name']} (Level {next_syllabus['level_no']})\n"
        prompt += f"Description: {next_syllabus.get('description', 'N/A')}\n"
        prompt += "\nTopics:\n"
        for topic in next_syllabus.get('topics', []):
            prompt += f"- {topic['name']}\n"
    else:
        prompt += "\n## Next Level Curriculum\nNo next level available. This is the final level in the track.\n"

    prompt += f"\n## Progression Status\n"
    if progression_status.get('enrolled'):
        prompt += f"Enrolled: Yes\n"
        prompt += f"Track ID: {progression_status['track_id']}\n"
        prompt += f"Blocked: {progression_status.get('is_blocked', False)}\n"
        if progression_status.get('level_progress'):
            lp = progression_status['level_progress']
            prompt += f"Level Status: {lp['status']}\n"
    else:
        prompt += "Student not enrolled in this track.\n"

    prompt += f"\n## Deterministic Analysis (Pre-computed)\n"
    prompt += "The following analysis has been computed deterministically from the evidence:\n\n"

    if deterministic_analysis.get('gaps'):
        prompt += "### Identified Gaps (ordered by priority)\n"
        for gap in deterministic_analysis['gaps']:
            prompt += f"""
**Priority {gap['priority']}: {gap['topic_name']}**
- Average Accuracy: {gap['avg_accuracy']*100:.1f}%
- Classification: {gap['classification']}
- Trend: {gap.get('trend', 'N/A')}
- Severity: {gap['severity']}
- Persistence Level: {gap.get('persistence_level', 'N/A')}
- Evidence: {gap['evidence']}
"""

    if deterministic_analysis.get('strengths'):
        prompt += "\n### Identified Strengths\n"
        for strength in deterministic_analysis['strengths']:
            prompt += f"- {strength['topic_name']}: {strength['accuracy']*100:.1f}% average\n"

    prompt += f"\n### Overall Confidence Assessment\n"
    prompt += f"Confidence Level: {deterministic_analysis['confidence']}\n"
    prompt += "Factors:\n"
    for factor in deterministic_analysis.get('confidence_factors', []):
        prompt += f"- {factor}\n"

    prompt += """

# YOUR TASK

Generate a comprehensive Skill Gap Analysis report with personalized learning recommendations.

## Output Requirements

1. **Summary** (2-3 sentences): Overall performance and key insight
2. **Overall Performance**: Assessment of student's current level mastery
3. **Strengths**: Topics where student demonstrates strong understanding
4. **Current Gaps**: Gaps from this assessment
5. **Persistent Gaps**: Gaps that have persisted across multiple attempts
6. **Trends**: Learning trends for key topics (improving/stable/declining/volatile)
7. **Difficulty Insights**: Patterns in performance across difficulty levels
8. **Next Level Readiness**: READY / NEEDS_TARGETED_PREPARATION / SIGNIFICANT_GAPS / INSUFFICIENT_DATA
9. **Next Level Topics**: Topics from next level curriculum (if available) and whether they require preparation
10. **Recommendations**: Prioritized, actionable learning recommendations
11. **Study Plan**: Structured sequence of learning activities
12. **Adaptive Assessment Plan**: Strategy for the next assessment (which topics to focus on, recommended difficulty)

## Recommendation Guidelines

- Base all recommendations on the supplied evidence and deterministic analysis
- For persistent gaps (Priority 1-3), provide specific practice direction
- For improving topics, acknowledge progress and suggest next steps
- For volatile performance, recommend building consistent understanding
- Connect current gaps to next-level readiness where appropriate
- Keep each recommendation to 2-3 sentences maximum

## Next Level Readiness Rules

- READY: No HIGH severity gaps, most topics above 70% accuracy
- NEEDS_TARGETED_PREPARATION: 1-2 HIGH severity gaps that need addressing
- SIGNIFICANT_GAPS: 3+ HIGH severity gaps or critical foundational weakness
- INSUFFICIENT_DATA: Only one attempt or inconsistent data

## Remember

- You are interpreting data, not measuring it
- The deterministic analysis has already done the mathematical work
- Your job is to synthesize evidence into personalized guidance
- Be specific, actionable, and encouraging where appropriate
- Never invent topics, scores, or prerequisites not in the supplied evidence

Generate the analysis now.
"""

    return prompt
