import os

try:


    from scaffold.local import local_api_config as _local_api_config
except ImportError:
    _local_api_config = None


def _local_value(name, default=""):

    if _local_api_config is None:
        return default
    return getattr(_local_api_config, name, default)


FAKE_API = os.environ.get("STATECLARIFY_FAKE_API", "true").lower() != "false"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or _local_value("API_KEY")


OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL") or _local_value(
    "API_BASE_URL", 'https://api.example.invalid/v1'
)
MODEL_NAME = os.environ.get("STATECLARIFY_MODEL") or _local_value("MODEL_NAME", "gpt-5.4-mini")
MODEL_TEMPERATURE = float(os.environ.get("STATECLARIFY_TEMPERATURE", "0"))


MODEL_TEMPERATURE_OVERRIDE = None


USE_JSON_RESPONSE_FORMAT = True


def effective_temperature():

    if MODEL_TEMPERATURE_OVERRIDE is not None:
        return MODEL_TEMPERATURE_OVERRIDE
    return MODEL_TEMPERATURE
MODEL_SEED = int(os.environ["STATECLARIFY_SEED"]) if os.environ.get("STATECLARIFY_SEED") else None


API_CONNECT_TIMEOUT_SECONDS = float(os.environ.get("STATECLARIFY_API_CONNECT_TIMEOUT", "15"))
API_READ_TIMEOUT_SECONDS = float(os.environ.get("STATECLARIFY_API_READ_TIMEOUT", "300"))
API_WRITE_TIMEOUT_SECONDS = float(os.environ.get("STATECLARIFY_API_WRITE_TIMEOUT", "30"))
API_POOL_TIMEOUT_SECONDS = float(os.environ.get("STATECLARIFY_API_POOL_TIMEOUT", "15"))
API_MAX_RETRIES = int(os.environ.get("STATECLARIFY_API_MAX_RETRIES", "0"))


API_CONNECTION_WAIT_TIMEOUT_SECONDS = float(
    os.environ.get("STATECLARIFY_API_CONNECTION_WAIT_TIMEOUT", "3600")
)
API_CONNECTION_RETRY_INTERVAL_SECONDS = float(
    os.environ.get("STATECLARIFY_API_CONNECTION_RETRY_INTERVAL", "30")
)
TRACE_API_CALLS = os.environ.get("STATECLARIFY_TRACE_API", "false").lower() == "true"


HUMAN_SIMULATOR_API_KEY = (
    os.environ.get("STATECLARIFY_HUMAN_API_KEY")
    or _local_value("HUMAN_SIMULATOR_API_KEY")
    or OPENAI_API_KEY
)
HUMAN_SIMULATOR_BASE_URL = (
    os.environ.get("STATECLARIFY_HUMAN_BASE_URL")
    or _local_value("HUMAN_SIMULATOR_API_BASE_URL")
    or OPENAI_BASE_URL
)
HUMAN_SIMULATOR_MODEL_NAME = (
    os.environ.get("STATECLARIFY_HUMAN_MODEL")
    or _local_value("HUMAN_SIMULATOR_MODEL_NAME")
    or MODEL_NAME
)


JUDGE_MODEL_NAME = os.environ.get("STATECLARIFY_JUDGE_MODEL", MODEL_NAME)
JUDGE_MIN_CONFIDENCE = float(os.environ.get("STATECLARIFY_JUDGE_MIN_CONFIDENCE", "0.7"))

SCAFFOLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(SCAFFOLD_ROOT)
MEMORY_STORE_PATH = os.path.join(SCAFFOLD_ROOT, "data", "memory_state.json")
