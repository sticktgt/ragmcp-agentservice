import os
import yaml
from pathlib import Path
from utils.logger import get_logger

logger = get_logger()

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"

def load_yaml_config(file_path: Path) -> dict:
    if not file_path.exists():
        logger.warning(f"Config file not found at {file_path}, using empty config.")
        return {}
    with open(file_path, "r") as f:
        return yaml.safe_load(f)

def apply_env_overrides(config: dict, prefix="") -> dict:
    for key, value in config.items():
        full_key = f"{prefix}__{key}".upper() if prefix else key.upper()
        if isinstance(value, dict):
            config[key] = apply_env_overrides(value, full_key)
        else:
            env_value = os.getenv(full_key)
            if env_value is not None:
                logger.debug(f"Overriding {full_key} from env")
                config[key] = _cast_type(env_value, type(value))
    return config

def _cast_type(value: str, desired_type):
    try:
        if desired_type == bool:
            return value.lower() in ("1", "true", "yes", "on")
        elif desired_type == int:
            return int(value)
        elif desired_type == float:
            return float(value)
        elif desired_type == list:
            return yaml.safe_load(value)
        else:
            return value
    except Exception as e:
        logger.warning(f"Could not cast value to {desired_type}: {e}")
        return value
    
def inject_dynamic_env_vars(config: dict, prefix="RS__") -> dict:
    for key, val in os.environ.items():
        if key.startswith(prefix):
            path = key[len(prefix):].split("__")
            cur = config
            for i, part in enumerate(path[:-1]):
                part_lower = part.lower()
                # Check if a case-insensitive match already exists
                matched_key = next((k for k in cur if k.lower() == part_lower), None)
                if matched_key is None:
                    matched_key = part_lower
                if not isinstance(cur.get(matched_key), dict):
                    cur[matched_key] = {}
                cur = cur[matched_key]

            last_key = path[-1].lower()
            # Same logic for the final key
            matched_last_key = next((k for k in cur if k.lower() == last_key), None)
            if matched_last_key is None:
                matched_last_key = last_key
            cur[matched_last_key] = _guess_type(val)
    return config


def _guess_type(val: str):
    try:
        parsed = yaml.safe_load(val)
        return parsed
    except Exception:
        return val


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    base_config = load_yaml_config(config_path)
    base_config = apply_env_overrides(base_config, "RS")
    # Inject dynamic environment variables (not in YAML, new names lower case only!)
    base_config = inject_dynamic_env_vars(base_config)
    
    return base_config

CONFIG = load_config()
