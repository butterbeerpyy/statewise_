import argparse
import json
import time

from openai import OpenAI

from scaffold.local import local_api_config


def _error_result(exc):
    return {
        "ok": False,
        "status": getattr(exc, "status_code", None),
        "error_type": type(exc).__name__,
        "message": str(exc)[:300],
    }


def list_models(profile_name, profile, timeout):
    started = time.perf_counter()
    try:
        client = OpenAI(
            api_key=profile["api_key"],
            base_url=profile["base_url"],
            timeout=timeout,
            max_retries=0,
        )
        page = client.models.list()
        result = {
            "ok": True,
            "status": 200,
            "models": [item.id for item in page.data],
        }
    except Exception as exc:
        result = _error_result(exc)
    result.update(
        {
            "profile": profile_name,
            "base_url": profile["base_url"],
            "elapsed_s": round(time.perf_counter() - started, 2),
        }
    )
    return result


def probe_chat(profile_name, profile, model, timeout):
    started = time.perf_counter()
    try:
        client = OpenAI(
            api_key=profile["api_key"],
            base_url=profile["base_url"],
            timeout=timeout,
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            temperature=0,
        )
        text = response.choices[0].message.content or ""
        result = {
            "ok": True,
            "status": 200,
            "response_preview": text[:80],
        }
    except Exception as exc:
        result = _error_result(exc)
    result.update(
        {
            "profile": profile_name,
            "model": model,
            "elapsed_s": round(time.perf_counter() - started, 2),
        }
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        action="append",
        choices=sorted(local_api_config.API_PROFILES),
        help="Profile to probe; repeat for several. Default: all profiles.",
    )
    parser.add_argument(
        "--models",
        default="",
        help="Comma-separated model IDs for minimal chat probes.",
    )
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()

    selected = args.profile or list(local_api_config.API_PROFILES)
    models = [item.strip() for item in args.models.split(",") if item.strip()]
    output = {"catalogs": [], "chat_probes": []}

    for profile_name in selected:
        profile = local_api_config.API_PROFILES[profile_name]
        output["catalogs"].append(list_models(profile_name, profile, args.timeout))
        for model in models:
            output["chat_probes"].append(
                probe_chat(profile_name, profile, model, args.timeout)
            )

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
