"""LLM Chain and Gemini integration module.

Phase 4 Implementation:
LangChain Expression Language (LCEL) pipeline combining:
- PromptTemplate (rich technical context, guardrails, and formatting instructions)
- ChatGoogleGenerativeAI (Gemini Flash model, temperature 0.1)
- JsonOutputParser (strict JSON extraction)
- Pydantic validation (PRReflection schema with 3-4 key learnings)
- Transparent diff truncation for large contexts
"""

import json
from typing import Any, Optional
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import ValidationError

from app.config import settings
from app.logging_config import logger
from app.models import ChangedFileModel, HydratedPRContext, LinkedIssueModel, PRReflection


class LLMChainError(Exception):
    """Exception raised for failures during LLM chain execution or validation."""


# Maximum patch characters sent to LLM to prevent context overflow while preserving fidelity
MAX_DIFF_CHARACTERS = 25000


def format_diff_for_llm(
    changed_files: list[ChangedFileModel],
    max_chars: int = MAX_DIFF_CHARACTERS,
) -> tuple[str, bool]:
    """Format file patches with transparent truncation when exceeding threshold."""
    formatted_chunks: list[str] = []
    current_chars = 0
    truncated = False

    for file in changed_files:
        header = f"--- File: {file.filename} (status: {file.status}, +{file.additions}/-{file.deletions}) ---\n"
        if not file.patch:
            chunk = f"{header}[No patch available - binary or large file]\n\n"
            formatted_chunks.append(chunk)
            current_chars += len(chunk)
            continue

        patch_str = file.patch
        chunk_len = len(header) + len(patch_str) + 2

        if current_chars + chunk_len > max_chars:
            remaining_allowance = max(0, max_chars - current_chars - len(header) - 150)
            if remaining_allowance > 200:
                truncated_patch = (
                    patch_str[:remaining_allowance]
                    + "\n... [Patch truncated for this file due to length limit] ...\n"
                )
                formatted_chunks.append(f"{header}{truncated_patch}\n")
            else:
                formatted_chunks.append(f"{header}[Patch omitted due to total diff length threshold]\n\n")
            truncated = True
            break
        else:
            formatted_chunks.append(f"{header}{patch_str}\n\n")
            current_chars += chunk_len

    combined_diff = "".join(formatted_chunks)
    if truncated:
        combined_diff += (
            "\n[NOTICE: Code diff was truncated to adhere to context length constraints. "
            "Analysis is grounded in the provided files and patch excerpts.]\n"
        )

    return combined_diff, truncated


def format_linked_issues_for_llm(linked_issues: list[LinkedIssueModel]) -> str:
    """Format linked issues into readable text for prompt inclusion."""
    if not linked_issues:
        return "No linked issues associated with this pull request."

    parts: list[str] = []
    for issue in linked_issues:
        body_preview = (
            issue.body.strip()[:600] + "..."
            if issue.body and len(issue.body) > 600
            else (issue.body or "No description provided.")
        )
        parts.append(
            f"- Issue #{issue.number}: {issue.title} (State: {issue.state}, Author: {issue.author})\n"
            f"  Description: {body_preview}"
        )
    return "\n\n".join(parts)


def format_changed_files_summary(changed_files: list[ChangedFileModel]) -> str:
    """Format a bulleted list of changed files with additions and deletions."""
    if not changed_files:
        return "No changed files recorded."
    return "\n".join(
        f"- {f.filename} ({f.status}: +{f.additions}/-{f.deletions})"
        for f in changed_files
    )


PROMPT_TEMPLATE_TEXT = """You are a senior software engineering lead and technical chronicler.
Your role is to analyze a merged pull request and extract grounded, high-value engineering insights.

### PULL REQUEST METADATA
- Repository: {repository}
- Pull Request Number: #{pr_number}
- PR Title: {pr_title}
- Author: {pr_author}

### PULL REQUEST DESCRIPTION
{pr_body}

### LINKED ISSUE CONTEXT
{linked_issues_context}

### CHANGED FILES
{changed_files_list}

### CODE DIFF / PATCH EVIDENCE
{diff_content}

---

### INSTRUCTIONS & GUARDRAILS
1. Use ONLY the supplied PR description, linked issue context, and diff evidence.
2. Do NOT invent implementation details or assume code behavior not supported by the diff/context.
3. Distinguish direct evidence from inference.
4. In 'issue_details', provide a concise explanation of the root cause of the bug OR the feature requirement.
5. In 'execution_summary', describe what was actually implemented, strictly grounded in the PR changes and files modified.
6. In 'key_learnings', produce concrete technical learnings (e.g. concurrency patterns, protocol semantics, API design, error recovery, data structures).
7. Avoid generic clichés (e.g. "testing is good", "clean code matters") unless specifically demonstrated by the technical change. Focus strictly on real engineering concepts demonstrated by this code.
8. 'key_learnings' MUST contain MINIMUM 3 and MAXIMUM 4 concise, high-impact technical points.
9. Return ONLY valid JSON matching the schema below. Do not wrap in markdown fences or write any preamble.

{format_instructions}
"""


class PRChroniclerChain:
    """LangChain LCEL pipeline for generating structured PR reflections via Gemini."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or settings.active_gemini_api_key
        self.model = model or settings.gemini_model
        self.parser = JsonOutputParser(pydantic_object=PRReflection)
        self.prompt = PromptTemplate(
            template=PROMPT_TEMPLATE_TEXT,
            input_variables=[
                "repository",
                "pr_number",
                "pr_title",
                "pr_author",
                "pr_body",
                "linked_issues_context",
                "changed_files_list",
                "diff_content",
            ],
            partial_variables={
                "format_instructions": self.parser.get_format_instructions(),
            },
        )
        logger.info(
            "PRChroniclerChain initialized with model '%s' (API key configured: %s).",
            self.model,
            bool(self.api_key),
        )

    def _build_chain(self, llm: Optional[Any] = None) -> Any:
        """Compose the LangChain Expression Language (LCEL) chain: prompt | llm | parser."""
        if llm is None:
            active_key = self.api_key or settings.active_gemini_api_key
            if not active_key:
                raise LLMChainError(
                    "Gemini API key is not configured. Please set GOOGLE_API_KEY or "
                    "GEMINI_API_KEY in your .env file or environment variables."
                )
            llm = ChatGoogleGenerativeAI(
                model=self.model,
                google_api_key=active_key,
                temperature=0.1,
            )
        # LCEL Composition: prompt | llm | parser
        return self.prompt | llm | self.parser

    async def generate_reflection(
        self,
        context: HydratedPRContext,
        custom_llm: Optional[Any] = None,
    ) -> PRReflection:
        """Synthesize a structured technical reflection from hydrated PR context.

        Args:
            context: HydratedPRContext populated with PR metadata, files, and diffs.
            custom_llm: Optional LLM instance for testing/mocking purposes.

        Returns:
            Validated PRReflection instance.
        """
        logger.info("LLM synthesis started for %s #%d", context.repository, context.pr_number)
        logger.info("Input diff character count: %d", context.diff_characters)

        # 1. Prepare prompt inputs with diff formatting & truncation guard
        diff_text, was_truncated = format_diff_for_llm(context.changed_files)
        if was_truncated:
            logger.info("Notice: Input diff exceeded threshold and was truncated safely.")

        prompt_inputs = {
            "repository": context.repository,
            "pr_number": context.pr_number,
            "pr_title": context.title,
            "pr_author": context.author,
            "pr_body": context.body or "No description provided.",
            "linked_issues_context": format_linked_issues_for_llm(context.linked_issues),
            "changed_files_list": format_changed_files_summary(context.changed_files),
            "diff_content": diff_text,
        }

        # 2. Build LCEL chain
        try:
            chain = self._build_chain(llm=custom_llm)
        except Exception as exc:
            logger.error("Failed to construct LCEL chain: %s", exc)
            raise LLMChainError(str(exc)) from exc

        # 3. Execute LCEL chain asynchronously: prompt | llm | parser
        try:
            raw_parsed = await chain.ainvoke(prompt_inputs)
        except Exception as exc:
            logger.error(
                "LLM synthesis failed for %s #%d: %s",
                context.repository,
                context.pr_number,
                type(exc).__name__,
            )
            raise LLMChainError(f"LCEL execution failed: {type(exc).__name__}") from exc

        # Log raw parsed JSON output (Requirement 8)
        logger.info("Raw parsed JSON output: %s", json.dumps(raw_parsed))

        # 4. Strict Pydantic validation
        try:
            reflection = PRReflection.model_validate(raw_parsed)
        except ValidationError as exc:
            logger.error(
                "Validation failed for %s #%d against PRReflection schema: %s",
                context.repository,
                context.pr_number,
                exc,
            )
            raise LLMChainError(f"Pydantic validation failed: {exc}") from exc

        logger.info(
            "Validation succeeded: PRReflection schema verified (key_learnings count: %d)",
            len(reflection.key_learnings),
        )
        logger.info("LLM synthesis succeeded for %s #%d", context.repository, context.pr_number)

        return reflection


# Default singleton chain instance
pr_chronicler_chain = PRChroniclerChain()
