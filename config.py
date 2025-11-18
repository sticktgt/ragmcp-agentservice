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
    for env_key, raw_val in os.environ.items():
        if not env_key.startswith(prefix):
            continue

        parts = [p for p in env_key[len(prefix):].split("__") if p]
        if not parts:
            continue

        cur = config
        created_sections = []
        # Walk/create intermediate sections, case-insensitive
        for part in parts[:-1]:
            part_l = part.lower()
            matched_key = next((k for k in cur.keys() if k.lower() == part_l), None)
            if matched_key is None:
                matched_key = part_l
                cur[matched_key] = {}
                created_sections.append(matched_key)
                #logger.debug(f"Created missing section '{matched_key}' for env {env_key}")
            elif not isinstance(cur[matched_key], dict):
                # Existing non-dict leaf; replace with dict to allow nesting
                logger.warning(f"Converting '{matched_key}' to object to inject subkeys for env {env_key}")
                cur[matched_key] = {}
            cur = cur[matched_key]

        last = parts[-1].lower()
        existing_last = next((k for k in cur.keys() if k.lower() == last), None)
        if existing_last is None:
            cur[last] = _guess_type(raw_val)
            # dot_path = ".".join([*created_sections, last]) if created_sections else last
            logger.debug(f"Injected {env_key} from env")
            # logger.info(f"Injected new config key from env: {env_key} -> path '{dot_path}'")
        else:
            # Do not overwrite here
            pass
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
