from structured_agents.grammar.config import DecodingConstraint

BASE_URL = "http://remora-server:8000/v1"
MODEL_NAME = "Qwen/Qwen3-4B-Instruct-2507-FP8"
API_KEY = "EMPTY"

GRAMMAR_CONFIG: DecodingConstraint | None = None
