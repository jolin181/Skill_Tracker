from __future__ import annotations

from question_paper_generator.models.input_models import PaperConfig
from question_paper_generator.prompts.validation_prompt import VALIDATION_SYSTEM_PROMPT
from question_paper_generator.services.distribution import build_blueprint


class ValidationAgent:
    def __init__(self):
        self.system_prompt = VALIDATION_SYSTEM_PROMPT

    def validate(self, input_data: dict) -> dict:
        config = PaperConfig.model_validate(input_data)
        blueprint = build_blueprint(
            config,
            config.difficulty_ratio.model_dump(),
            config.bloom_level_ratio.model_dump(),
        )
        return {
            "config": config,
            "blueprint": blueprint,
        }
