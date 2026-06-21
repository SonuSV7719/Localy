"""
Localy Benchmark Service.

Orchestrates standardized performance benchmark runs, collects metrics (TTFT, tokens/sec),
saves results, and compares them with previous runs or baselines.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from localy.core.config import Settings
from localy.core.exceptions import BenchmarkError
from localy.core.logging import get_logger
from localy.inference.engine import get_engine
from localy.inference.types import GenerationConfig, InferenceRequest

if TYPE_CHECKING:
    from localy.services.model_service import ModelService

logger = get_logger(__name__)


class BenchmarkService:
    """Manages system benchmarking using loaded LLMs."""

    def __init__(self, settings: Settings, model_service: ModelService) -> None:
        self._settings = settings
        self._model_service = model_service

    async def run_benchmark(self, model_spec: str, iterations: int = 3) -> dict[str, Any]:
        """Run a standardized benchmark on the specified model.

        Measures:
        - Time-To-First-Token (TTFT) in ms
        - Prompt processing speed (tokens/sec)
        - Generation speed (tokens/sec)

        Runs multiple iterations and returns the median results.
        """
        logger.info("starting_benchmark_run", model_spec=model_spec, iterations=iterations)

        # Ensure model is loaded
        try:
            active_model = await self._model_service.get_active_model()
            if active_model is None or active_model.model_id != model_spec:
                await self._model_service.load_model(model_spec)
        except Exception as e:
            raise BenchmarkError(f"Failed to load model '{model_spec}' for benchmark: {e}") from e

        engine = get_engine(self._settings)

        # Standardized benchmark prompts
        prompt = (
            "Explain the difference between a list and a tuple in Python, "
            "and when you should use each. Keep it concise."
        )

        warmup_prompt = "Hello, warm up please."

        # 1. Warm-up run (discarded)
        try:
            await engine.generate(
                InferenceRequest(
                    prompt=warmup_prompt,
                    generation_config=GenerationConfig(max_tokens=20, temperature=0.0),
                )
            )
        except Exception as e:
            raise BenchmarkError(f"Warmup run failed: {e}") from e

        # 2. Benchmark iterations
        results: list[dict[str, float]] = []

        for i in range(iterations):
            logger.info("running_benchmark_iteration", iteration=i + 1, total=iterations)
            start = time.perf_counter()
            first_token_time = None
            tokens_generated = 0

            try:
                # We use streaming to measure TTFT and generation tokens/sec
                async for chunk in engine.generate_stream(
                    InferenceRequest(
                        prompt=prompt,
                        generation_config=GenerationConfig(max_tokens=150, temperature=0.0),
                    )
                ):
                    if chunk.token:
                        if first_token_time is None:
                            first_token_time = time.perf_counter()
                        tokens_generated += 1

                end = time.perf_counter()
                total_time = end - start

                if first_token_time is None:
                    raise BenchmarkError("No tokens were generated during benchmark run.")

                ttft_ms = (first_token_time - start) * 1000
                gen_speed = tokens_generated / (end - first_token_time) if (end - first_token_time) > 0 else 0

                results.append(
                    {
                        "total_time_seconds": total_time,
                        "ttft_ms": ttft_ms,
                        "generation_speed_tps": gen_speed,
                        "tokens_generated": float(tokens_generated),
                    }
                )

            except Exception as e:
                logger.error("benchmark_iteration_failed", iteration=i + 1, error=str(e))
                raise BenchmarkError(f"Benchmark iteration {i + 1} failed: {e}") from e

        # 3. Calculate median values
        import statistics

        median_ttft = statistics.median([r["ttft_ms"] for r in results])
        median_speed = statistics.median([r["generation_speed_tps"] for r in results])
        median_time = statistics.median([r["total_time_seconds"] for r in results])
        avg_tokens = statistics.mean([r["tokens_generated"] for r in results])

        report = {
            "model_id": model_spec,
            "iterations_run": iterations,
            "timestamp": time.time(),
            "median_generation_speed_tps": round(median_speed, 2),
            "median_ttft_ms": round(median_ttft, 1),
            "median_total_time_seconds": round(median_time, 2),
            "avg_tokens_generated": round(avg_tokens, 1),
            "raw_runs": results,
        }

        # 4. Save results
        self._settings.benchmarks_path.mkdir(parents=True, exist_ok=True)
        filename = f"benchmark_{model_spec.replace(':', '_')}_{int(time.time())}.json"
        path = self._settings.benchmarks_path / filename
        path.write_text(json.dumps(report, indent=2))

        logger.info(
            "benchmark_run_completed",
            tps=report["median_generation_speed_tps"],
            ttft=report["median_ttft_ms"],
        )
        return report

    def get_history(self) -> list[dict[str, Any]]:
        """Get history of all saved benchmark runs."""
        history = []
        if not self._settings.benchmarks_path.exists():
            return history

        for path in self._settings.benchmarks_path.glob("benchmark_*.json"):
            try:
                data = json.loads(path.read_text())
                data["filename"] = path.name
                history.append(data)
            except Exception as e:
                logger.warning("failed_to_load_benchmark_history_file", path=str(path), error=str(e))

        return sorted(history, key=lambda x: x.get("timestamp", 0), reverse=True)
