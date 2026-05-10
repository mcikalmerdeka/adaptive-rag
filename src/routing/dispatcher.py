"""Strategy dispatcher: execute the router's decision.

This is the single entry point the chat UI calls. Lazily wires up
:class:`RetrievalPipeline`, :class:`SqlTool`, :class:`GroundedAnswerer`
and :class:`AdaptiveRouter` on first use so the app starts fast even when
SQL or OpenAI aren't configured.

The SQL tool is **optional**: if ``SQL_DATABASE_URL`` is unset (or the
connection fails on first use), the dispatcher continues without it and
the router is told to never pick SQL strategies.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from src.observability import flush_traces, span
from src.retrieval import RetrievalPipeline, RetrievedChunk
from src.synthesis import AnswerResponse, GroundedAnswerer, SynthesisError
from src.tools import SqlResult, SqlTool, SqlToolError

from .adaptive_router import AdaptiveRouter, RouterDecision
from .strategies import STRATEGY_LABELS, Strategy

logger = logging.getLogger(__name__)


@dataclass
class StageTimings:
    routing_ms: float = 0.0
    retrieval_ms: float = 0.0
    sql_ms: float = 0.0
    synthesis_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        return self.routing_ms + self.retrieval_ms + self.sql_ms + self.synthesis_ms


@dataclass
class AdaptiveAnswer:
    """Everything one chat turn produced.

    The chat UI consumes this; it carries enough info to render the
    answer, the sources panel, the executed SQL and the per-stage
    timings.
    """

    answer: str
    strategy: Strategy
    decision: RouterDecision
    response: AnswerResponse | None = None
    sql_result: SqlResult | None = None
    chunks: list[RetrievedChunk] = field(default_factory=list)
    timings: StageTimings = field(default_factory=StageTimings)
    notes: list[str] = field(default_factory=list)

    @property
    def strategy_label(self) -> str:
        return STRATEGY_LABELS.get(self.strategy, self.strategy.value)


class DispatchError(Exception):
    """Raised when dispatch can't recover from a downstream failure."""


class AdaptiveDispatcher:
    """Compose router + retrieval + SQL + synthesis."""

    def __init__(
        self,
        *,
        retrieval: RetrievalPipeline | None = None,
        sql_tool: SqlTool | None | bool = None,
        synthesizer: GroundedAnswerer | None = None,
        router: AdaptiveRouter | None = None,
    ) -> None:
        # Retrieval / synth are cheap; init lazily on first use to keep
        # app startup snappy and surface API key issues only when needed.
        self._retrieval_override = retrieval
        self._retrieval: RetrievalPipeline | None = retrieval

        self._synth_override = synthesizer
        self._synth: GroundedAnswerer | None = synthesizer

        # SQL tool: ``False`` disables it entirely. ``None`` means "try to
        # build on first use, fall back gracefully if it fails".
        self._sql_disabled = sql_tool is False
        self._sql_override = sql_tool if isinstance(sql_tool, SqlTool) else None
        self._sql: SqlTool | None = self._sql_override

        # Router needs to know whether SQL is available, so we init it
        # lazily after we've probed the SQL backend.
        self._router_override = router
        self._router: AdaptiveRouter | None = router

    # ---- public API ---------------------------------------------------

    def answer(
        self,
        query: str,
        *,
        history: Iterable[dict[str, str]] | None = None,
    ) -> AdaptiveAnswer:
        history_list = list(history) if history else []

        # One Langfuse trace per chat turn. Children (router / retrieval /
        # SQL / synthesis) inherit the trace context automatically.
        with span(
            "chat.turn",
            input={"query": query, "history_len": len(history_list)},
            metadata={"history_len": len(history_list)},
        ) as turn_span:
            try:
                result = self._answer_inner(query, history_list)
                turn_span.update(
                    output={
                        "answer": result.answer,
                        "strategy": result.strategy.value,
                    },
                    metadata={
                        "strategy": result.strategy.value,
                        "reasoning": result.decision.reasoning,
                        "routing_ms": result.timings.routing_ms,
                        "retrieval_ms": result.timings.retrieval_ms,
                        "sql_ms": result.timings.sql_ms,
                        "synthesis_ms": result.timings.synthesis_ms,
                        "total_ms": result.timings.total_ms,
                        "n_chunks": len(result.chunks),
                        "sql_executed": (
                            result.sql_result.sql if result.sql_result else None
                        ),
                        "notes": result.notes or None,
                    },
                )
                return result
            finally:
                # Short-lived script — flush so traces don't sit in the
                # background queue across a Gradio request boundary.
                flush_traces()

    def _answer_inner(
        self,
        query: str,
        history_list: list[dict[str, str]],
    ) -> AdaptiveAnswer:
        sql_tool = self._get_sql_tool()
        router = self._get_router(sql_tool)

        with span(
            "router.classify",
            input={"query": query},
            metadata={"sql_available": sql_tool is not None},
        ) as router_span:
            decision, routing_ms = router.classify(query, history=history_list)
            router_span.update(
                output={
                    "strategy": decision.strategy.value,
                    "reasoning": decision.reasoning,
                    "vector_query": decision.vector_query,
                    "sql_intent": decision.sql_intent,
                    "clarification_question": decision.clarification_question,
                },
                metadata={"latency_ms": routing_ms},
            )

        timings = StageTimings(routing_ms=routing_ms)
        notes: list[str] = []

        try:
            if decision.strategy == Strategy.CLARIFY:
                return self._handle_clarify(decision, timings, notes)

            if decision.strategy == Strategy.NO_RETRIEVAL:
                return self._handle_no_retrieval(query, decision, history_list, timings, notes)

            chunks: list[RetrievedChunk] = []
            sql_result: SqlResult | None = None

            if decision.strategy in (Strategy.VECTOR_ONLY, Strategy.HYBRID):
                chunks = self._do_retrieval(decision, query, timings)

            if decision.strategy in (Strategy.SQL_ONLY, Strategy.HYBRID):
                sql_result = self._do_sql(decision, query, sql_tool, timings, notes)

            return self._handle_synthesis(
                query=query,
                decision=decision,
                chunks=chunks,
                sql_result=sql_result,
                history=history_list,
                timings=timings,
                notes=notes,
            )
        except DispatchError:
            raise
        except Exception as exc:
            logger.exception("Unexpected dispatch failure")
            raise DispatchError(f"Adaptive dispatch failed: {exc}") from exc

    @property
    def sql_available(self) -> bool:
        return self._get_sql_tool() is not None

    @property
    def schema_summary(self) -> str:
        tool = self._get_sql_tool()
        return tool.schema_summary() if tool is not None else ""

    # ---- handlers -----------------------------------------------------

    def _handle_clarify(
        self,
        decision: RouterDecision,
        timings: StageTimings,
        notes: list[str],
    ) -> AdaptiveAnswer:
        question = (
            decision.clarification_question
            or "Could you give me a bit more detail about what you want to know?"
        )
        return AdaptiveAnswer(
            answer=question,
            strategy=Strategy.CLARIFY,
            decision=decision,
            timings=timings,
            notes=notes,
        )

    def _handle_no_retrieval(
        self,
        query: str,
        decision: RouterDecision,
        history: list[dict[str, str]],
        timings: StageTimings,
        notes: list[str],
    ) -> AdaptiveAnswer:
        synth = self._get_synth()
        with span("synthesis.direct", input={"query": query}) as synth_span:
            t0 = time.perf_counter()
            try:
                response = synth.answer_direct(query, history=history)
            except SynthesisError as exc:
                raise DispatchError(str(exc)) from exc
            timings.synthesis_ms = (time.perf_counter() - t0) * 1000
            synth_span.update(
                output={"answer": response.answer},
                metadata={
                    "model": response.model,
                    "latency_ms": timings.synthesis_ms,
                },
            )
        return AdaptiveAnswer(
            answer=response.answer,
            strategy=Strategy.NO_RETRIEVAL,
            decision=decision,
            response=response,
            timings=timings,
            notes=notes,
        )

    def _do_retrieval(
        self,
        decision: RouterDecision,
        query: str,
        timings: StageTimings,
    ) -> list[RetrievedChunk]:
        from src.config import settings

        retrieval = self._get_retrieval()
        search_query = decision.effective_vector_query(query)
        with span(
            "retrieval.hybrid_search",
            input={"query": search_query, "rephrased": search_query != query},
        ) as retr_span:
            report = retrieval.retrieve(search_query)
            timings.retrieval_ms = report.fused_ms + report.rerank_ms
            retr_span.update(
                output={
                    "n_chunks": len(report.chunks),
                    "top_labels": [c.citation_label() for c in report.chunks[:5]],
                },
                metadata={
                    "fused_count": report.fused_count,
                    "final_count": report.final_count,
                    "reranker_used": report.reranker_used,
                    "fused_ms": report.fused_ms,
                    "rerank_ms": report.rerank_ms,
                    "prefetch_k": settings.RETRIEVAL_PREFETCH_K,
                    "rerank_top_k": settings.RERANK_TOP_K,
                    "reranker_model": settings.RERANKER_MODEL,
                },
            )
            return report.chunks

    def _do_sql(
        self,
        decision: RouterDecision,
        query: str,
        sql_tool: SqlTool | None,
        timings: StageTimings,
        notes: list[str],
    ) -> SqlResult | None:
        if sql_tool is None:
            notes.append("SQL backend unavailable — skipped SQL step.")
            return None

        intent = decision.effective_sql_intent(query)
        with span("tool.sql_execute", input={"intent": intent}) as sql_span:
            t0 = time.perf_counter()
            try:
                result = sql_tool.answer(intent)
            except SqlToolError as exc:
                logger.warning(f"SQL tool failed: {exc}")
                notes.append(f"SQL step failed: {exc}")
                sql_span.update(
                    output={"error": str(exc)},
                    metadata={"failed": True},
                )
                return None
            finally:
                timings.sql_ms = (time.perf_counter() - t0) * 1000
            sql_span.update(
                output={
                    "sql": result.sql,
                    "row_count": result.row_count,
                    "columns": result.columns,
                    "rows_preview": result.rows[:5],
                },
                metadata={
                    "elapsed_ms": result.elapsed_ms,
                    "truncated": result.truncated,
                    "row_count": result.row_count,
                },
            )
        return result

    def _handle_synthesis(
        self,
        *,
        query: str,
        decision: RouterDecision,
        chunks: list[RetrievedChunk],
        sql_result: SqlResult | None,
        history: list[dict[str, str]],
        timings: StageTimings,
        notes: list[str],
    ) -> AdaptiveAnswer:
        synth = self._get_synth()

        # If both retrieval and SQL produced nothing, return a clear
        # "nothing to ground on" message instead of asking the LLM to
        # hallucinate.
        if not chunks and sql_result is None:
            empty_msg = (
                "I tried to look this up but came back empty. "
                "Either nothing relevant is indexed yet, or the database "
                "step couldn't run. Try ingesting more sources or rephrasing."
            )
            return AdaptiveAnswer(
                answer=empty_msg,
                strategy=decision.strategy,
                decision=decision,
                chunks=chunks,
                sql_result=sql_result,
                timings=timings,
                notes=notes,
            )

        with span(
            "synthesis.grounded",
            input={
                "query": query,
                "n_chunks": len(chunks),
                "has_sql": sql_result is not None,
            },
        ) as synth_span:
            t0 = time.perf_counter()
            try:
                if sql_result is not None:
                    response = synth.answer_with_sql(
                        query, chunks, sql_result, history=history
                    )
                else:
                    response = synth.answer(query, chunks, history=history)
            except SynthesisError as exc:
                raise DispatchError(str(exc)) from exc
            timings.synthesis_ms = (time.perf_counter() - t0) * 1000
            synth_span.update(
                output={
                    "answer": response.answer,
                    "cited_indices": response.cited_indices,
                    "cited_db": response.cited_db,
                },
                metadata={
                    "model": response.model,
                    "latency_ms": timings.synthesis_ms,
                    "n_citations": len(response.citations),
                },
            )

        return AdaptiveAnswer(
            answer=response.answer,
            strategy=decision.strategy,
            decision=decision,
            response=response,
            sql_result=sql_result,
            chunks=chunks,
            timings=timings,
            notes=notes,
        )

    # ---- lazy initializers --------------------------------------------

    def _get_retrieval(self) -> RetrievalPipeline:
        if self._retrieval is None:
            self._retrieval = RetrievalPipeline()
        return self._retrieval

    def _get_synth(self) -> GroundedAnswerer:
        if self._synth is None:
            self._synth = GroundedAnswerer()
        return self._synth

    def _get_sql_tool(self) -> SqlTool | None:
        if self._sql_disabled:
            return None
        if self._sql is None and self._sql_override is None:
            try:
                self._sql = SqlTool()
            except SqlToolError as exc:
                logger.info(
                    f"SQL tool unavailable, dispatcher will skip SQL strategies: {exc}"
                )
                self._sql_disabled = True
                return None
        return self._sql

    def _get_router(self, sql_tool: SqlTool | None) -> AdaptiveRouter:
        if self._router is None:
            self._router = AdaptiveRouter(
                sql_available=sql_tool is not None,
                schema_summary=sql_tool.schema_summary() if sql_tool else "",
            )
        return self._router
