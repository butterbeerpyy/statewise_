import os


def _profile(number):
    prefix = f"STATEWISE_API_{number:02d}"
    return {
        "base_url": os.environ.get(f"{prefix}_BASE_URL", os.environ.get("OPENAI_BASE_URL", "https://api.example.invalid/v1")),
        "api_key": os.environ.get(f"{prefix}_KEY", os.environ.get("OPENAI_API_KEY", "")),
        "model_name": os.environ.get(f"{prefix}_MODEL", os.environ.get("STATECLARIFY_MODEL", "model-name")),
    }


API_PROFILES = {f"api_{number:02d}": _profile(number) for number in range(1, 4)}
ACTIVE_API_PROFILE = os.environ.get("STATEWISE_API_PROFILE", "api_01")
API_ROLES = {
    "main_agent": ACTIVE_API_PROFILE,
    "human_simulator": os.environ.get("STATEWISE_HUMAN_API_PROFILE", ACTIVE_API_PROFILE),
}
API_BASE_URL = API_PROFILES[ACTIVE_API_PROFILE]["base_url"]
API_KEY = API_PROFILES[ACTIVE_API_PROFILE]["api_key"]
MODEL_NAME = API_PROFILES[ACTIVE_API_PROFILE]["model_name"]
HUMAN_SIMULATOR_API_BASE_URL = API_PROFILES[API_ROLES["human_simulator"]]["base_url"]
HUMAN_SIMULATOR_API_KEY = API_PROFILES[API_ROLES["human_simulator"]]["api_key"]
HUMAN_SIMULATOR_MODEL_NAME = API_PROFILES[API_ROLES["human_simulator"]]["model_name"]
