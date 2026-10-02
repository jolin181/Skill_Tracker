# AI Engine Module

Provides AI-powered features for the platform including question generation and skill gap analysis.

## Components

### 1. Question Generation
Generates exam questions for the question bank using LLM inference on topic/subtopic text.

**Key Design Principles:**
- **No source documents** — questions are generated from `topic.name`, `topic.description`, `subtopic.name`, `subtopic.description` only.
- Output must pass `question_validator.py` before being stored.
- Target difficulty is computed from the student's historical accuracy (`difficulty.py`).

**Difficulty Rules:**
| Accuracy | Target Difficulty |
|---|---|
| > 80% | hard |
| 50% – 80% | medium |
| < 50% | easy |
| No data (first attempt) | medium |

### 2. Skill Gap Analysis Agent

**Purpose:** Convert analytical measurements into personalized learning decisions.

**Critical Architecture Distinction:**

```
ANALYTICS MODULE (teammate's work)
  ↓
Answers: "WHAT happened?"
  ↓
Example: Linked Lists = 44% avg accuracy across 3 attempts
───────────────────────────────────────────────────────────
SKILL GAP AGENT (this module)
  ↓
Answers: "WHAT does it mean for THIS student?"
Answers: "WHAT should THIS student do next?"
  ↓
Example: Persistent gap requiring targeted practice before progression
```

**Agent Architecture:**

The Skill Gap Agent is a genuinely agentic system combining:
1. **Tool-driven evidence retrieval** from Analytics and other modules
2. **Deterministic analysis** (gap classification, trend analysis, confidence scoring)
3. **LLM reasoning** for interpretation and personalization
4. **Structured output** with Pydantic validation

**Agent Workflow:**
```
Student Assessment
    ↓
Existing Scoring System
    ↓
Result + TopicResult
    ↓
Analytics Layer (Evidence)
    ↓
┌─────────────────────────────────────┐
│     SKILL GAP AGENT                 │
│                                     │
│  Tools:                             │
│  • get_current_assessment_result    │
│  • get_topic_performance (Analytics)│
│  • get_student_history              │
│  • get_difficulty_performance       │
│  • get_current_level_syllabus       │
│  • get_next_level_syllabus          │
│  • get_progression_status           │
│                                     │
│  Deterministic Analysis:            │
│  • classify_gap                     │
│  • analyze_trend                    │
│  • calculate_confidence             │
│  • calculate_severity               │
│  • prioritize_gaps                  │
│  • analyze_difficulty_pattern       │
│                                     │
│  LLM Reasoning:                     │
│  • Grounded prompt with evidence    │
│  • Structured output validation     │
│  • Never invents facts/scores       │
└─────────────────────────────────────┘
    ↓
Personalized Analysis
    ↓
Study Plan + Recommendations
    ↓
Adaptive Assessment Strategy
    ↓
Student Dashboard
    ↓
Next Assessment (feedback loop)
```

**Data Hierarchy:**

```
DATABASE FACTS
      >
DETERMINISTIC CALCULATIONS
      >
LLM REASONING
```

The LLM NEVER calculates scores or invents curriculum. All numerical analysis is deterministic.

**Gap Classification:**
- **PERSISTENT**: Below threshold across multiple attempts (HIGH/MEDIUM persistence)
- **CURRENT**: Below threshold in latest attempt only
- **IMPROVING**: Below threshold but showing upward trend

**Trend Analysis:**
- **IMPROVING**: Accuracy increasing >5% per attempt
- **DECLINING**: Accuracy decreasing >5% per attempt
- **STABLE**: Consistent performance (±5%)
- **VOLATILE**: High variance across attempts
- **INSUFFICIENT_DATA**: < 2 attempts

**Confidence Scoring:**
- **HIGH**: 3+ attempts, consistent pattern, rich evidence
- **MEDIUM**: 2 attempts or some data limitations
- **LOW**: Single attempt or insufficient evidence

**Next Level Readiness:**
- **READY**: No HIGH severity gaps, most topics >70%
- **NEEDS_TARGETED_PREPARATION**: 1-2 HIGH severity gaps
- **SIGNIFICANT_GAPS**: 3+ HIGH severity gaps
- **INSUFFICIENT_DATA**: Limited assessment history

**LLM Failure Handling:**

The assessment workflow MUST NOT depend on LLM availability. If the LLM is unavailable:
1. Assessment scoring still completes normally
2. Deterministic analysis is computed and returned
3. Analysis is marked as LLM-unavailable
4. Can be regenerated later when LLM is available

**API Endpoints:**

- `POST /api/v1/ai-engine/skill-gap/analyze` - Trigger analysis for an attempt
- `GET /api/v1/ai-engine/skill-gap/latest` - Get latest analysis for authenticated student
- `GET /api/v1/ai-engine/skill-gap/{attempt_id}` - Get analysis for specific attempt

All endpoints enforce authorization: students can only access their own analyses.

**Database Models:**

- `SkillGapReport`: Stores complete analysis with recommendations and study plan
- `SkillGapItem`: Stores individual skill gap items with evidence and classification

**Feedback Loop:**

The agent supports continuous improvement:
```
Assessment 1 → Analysis 1 → Recommendations
    ↓
Student Practice
    ↓
Assessment 2 → Analysis 2 → Compares with Analysis 1
    ↓
Detects: Gap improved / Gap persists / Gap worsened
    ↓
Updated Recommendations
```

## File Layout

```
ai_engine/
├── __init__.py
├── router.py                    # API endpoints (skill gap + questions)
├── models.py                    # Question, QuestionOption, SkillGapReport, SkillGapItem
├── schemas.py                   # Pydantic schemas for structured output
├── question_generator.py        # Question generation pipeline
├── difficulty.py                # Accuracy → difficulty mapping
├── skill_gap.py                 # Agent tools, deterministic analysis, orchestration
├── question_validator.py        # Question output validation
├── llm_client.py                # OpenAI async client with structured output
├── prompts/
│   ├── __init__.py
│   └── skill_gap_agent.py       # Grounding prompt for agent
├── README.md
└── tests/
```

## Module Interactions

**Question Generation:**
- Reads topic/subtopic content via `domains/service` (name + description only)
- Reads student accuracy from `analytics` summary tables
- Persists to `Question` / `QuestionOption` tables

**Skill Gap Analysis:**
- Reads evidence from `analytics/service` (TopicGapSummary, DifficultyPerformanceSummary)
- Reads attempt data from `attempts/service`
- Reads curriculum from `domains/service`
- Reads progression from `progress/service`
- **Does NOT duplicate Analytics** - uses it as an evidence layer
- Persists to `SkillGapReport` / `SkillGapItem` tables

## Configuration

Required environment variables in `.env`:
```
LLM_PROVIDER=openai
LLM_API_KEY=your_openai_api_key
LLM_MODEL=gpt-4o
```

If `LLM_API_KEY` is not set, skill gap analysis will return deterministic analysis only.
