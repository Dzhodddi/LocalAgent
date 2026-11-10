"""Measure Ollama speed for different load settings: how many layers on the GPU, context size, CPU threads.

Each combination reloads the model, sends one warm-up and `--runs` measured requests (a
fresh prompt each time, so nothing comes from the prompt cache) and reports:
  - gpu %: share of the model in VRAM (from /api/ps)
  - prompt tok/s: reading speed (matters for long agent prompts)
  - output tok/s: generation speed

Server-wide settings (OLLAMA_NUM_PARALLEL, OLLAMA_KV_CACHE_TYPE, OLLAMA_FLASH_ATTENTION)
cannot be set per request: change them in the systemd override, restart Ollama and run this
again. The current ones are printed at the top.

Usage: uv run python scripts/bench_gpu.py [--model M] [--num-gpu auto,20,24] [--num-ctx 8192,16384]
                                          [--num-thread auto,6] [--runs 2]
"""

import argparse
import itertools
import subprocess
import time

import ollama

from localagents.config import Settings

# About 1.5k tokens of code-like text, close to what the agent sends.
PROMPT_BODY = "\n".join(
    f"def handler_{i}(request):\n    value = request.get('field_{i}', {i})\n    return value * {i % 7 + 1}\n"
    for i in range(60)
)


def server_env() -> str:
    out = subprocess.run(
        ["systemctl", "show", "ollama", "-p", "Environment"], capture_output=True, text=True, check=False
    ).stdout
    return " ".join(part for part in out.split() if part.startswith("OLLAMA_") and "MODELS" not in part)


def parse_list(text: str) -> list[int | None]:
    return [None if item == "auto" else int(item) for item in text.split(",")]


def measure(client: ollama.Client, model: str, options: dict, runs: int) -> dict:
    client.generate(model=model, prompt="hi", options=options | {"num_predict": 1}, keep_alive="10m")  # load
    loaded = next((m for m in client.ps().models if m.model == model), None)
    gpu = loaded.size_vram / loaded.size if loaded and loaded.size else 0.0
    prompt_tps, output_tps = [], []
    for run in range(runs):
        prompt = (
            f"Run {run} at {time.time()}. Summarize what these handlers do in two sentences.\n\n{PROMPT_BODY}"
        )
        r = client.generate(
            model=model,
            prompt=prompt,
            options=options | {"num_predict": 200, "temperature": 0},
            keep_alive="10m",
        )
        prompt_tps.append(r.prompt_eval_count / (r.prompt_eval_duration / 1e9))
        output_tps.append(r.eval_count / (r.eval_duration / 1e9))
    return {
        "gpu": gpu,
        "vram_gb": (loaded.size_vram if loaded else 0) / 1e9,
        "prompt_tps": sum(prompt_tps) / runs,
        "output_tps": sum(output_tps) / runs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=Settings().model)
    parser.add_argument(
        "--num-gpu", default="auto", help="Layers on the GPU, comma separated; auto = Ollama decides."
    )
    parser.add_argument("--num-ctx", default=str(Settings().num_ctx), help="Context sizes, comma separated.")
    parser.add_argument("--num-thread", default="auto", help="CPU threads, comma separated.")
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()

    client = ollama.Client(host=Settings().ollama_host, timeout=900)
    print(f"server: {server_env()}\nmodel: {args.model}\n")
    print(
        f"{'num_gpu':>7} {'num_ctx':>7} {'threads':>7} {'gpu %':>6} {'vram GB':>7} {'prompt tok/s':>12} {'output tok/s':>12}"
    )
    combos = itertools.product(
        parse_list(args.num_gpu), parse_list(args.num_ctx), parse_list(args.num_thread)
    )
    for num_gpu, num_ctx, num_thread in combos:
        options = {
            k: v
            for k, v in {"num_gpu": num_gpu, "num_ctx": num_ctx, "num_thread": num_thread}.items()
            if v is not None
        }
        try:
            r = measure(client, args.model, options, args.runs)
        except ollama.ResponseError as e:  # e.g. out of VRAM with too many layers
            print(
                f"{num_gpu or 'auto':>7} {num_ctx or '-':>7} {num_thread or 'auto':>7}  failed: {e.error[:60]}"
            )
            continue
        print(
            f"{num_gpu or 'auto':>7} {num_ctx or '-':>7} {num_thread or 'auto':>7} {r['gpu']:>6.0%} "
            f"{r['vram_gb']:>7.1f} {r['prompt_tps']:>12.0f} {r['output_tps']:>12.1f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
