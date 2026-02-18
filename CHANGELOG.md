# Msty Admin MCP — Changelog

## v5.0.0 — 2024

### Major Changes

#### Architecture: Msty 2.4.0+ Port-Based Service Discovery
- Replaced process-based service detection with port-based discovery
- Services now exposed via ports: Local AI (11964), MLX (11973), LLaMA.cpp (11454), Vibe CLI Proxy (8317)
- Environment variables: `MSTY_HOST`, `MSTY_AI_PORT`, `MSTY_MLX_PORT`, `MSTY_LLAMACPP_PORT`, `MSTY_VIBE_PORT`
- Fully backwards compatible with Msty 2.4.0+ installations

#### Phase 3 Expansion: New Service Backend Tools
- **MLX Integration** (2 tools):
  - `list_mlx_models`: Enumerate MLX models available locally
  - `chat_with_mlx_model`: Chat with MLX models
- **LLaMA.cpp Integration** (2 tools):
  - `list_llamacpp_models`: Enumerate LLaMA.cpp models
  - `chat_with_llamacpp_model`: Chat with LLaMA.cpp models
- **Vibe CLI Proxy** (2 tools):
  - `get_vibe_proxy_status`: Check Vibe CLI proxy health
  - `query_vibe_proxy`: Query Vibe proxy services

#### Phase 6: Bloom Behavioral Evaluation
- Complete Bloom integration for evaluating local LLM behaviors
- Detects: sycophancy, hallucination, overconfidence, scope-creep, task-quality-degradation, certainty-calibration, context-window-degradation, instruction-following
- Custom behavior definitions via `cv_behaviors.py`
- Quality thresholds by task category (research_analysis, data_processing, advisory_tasks, general_tasks)
- Handoff triggers for escalation to Claude
- Requires Anthropic API key for judge model (Claude Sonnet 4 recommended)
- Tools: `bloom_evaluate_model`, `bloom_check_handoff`, `bloom_get_history`, `bloom_list_behaviors`, `bloom_get_thresholds`, `bloom_validate_model`

#### Transport: Streamable HTTP
- Run MCP server as standalone HTTP endpoint
- `--transport streamable-http` flag
- Remote access to MCP tools via HTTP
- Uvicorn/Starlette backend
- Perfect for distributed Msty deployments

### Tool Summary (36 Total)

**Phase 1: Foundational (6 tools)**
- `detect_msty_installation`: Locate Msty installation and configuration
- `read_msty_database`: Query Msty SQLite database directly
- `list_configured_tools`: List all Msty tools
- `get_model_providers`: List available model providers
- `analyse_msty_health`: Get comprehensive system health report
- `get_server_status`: Check MCP server health

**Phase 2: Configuration (4 tools)**
- `export_tool_config`: Export Msty tool configurations
- `sync_claude_preferences`: Sync Claude preferences with Msty
- `generate_persona`: Create AI personas for Msty
- `import_tool_config`: Import tool configurations

**Phase 3: Service Integration (11 tools)**
- `get_service_status`: Check all service backends
- `list_available_models`: List all available models across services
- `query_local_ai_service`: Query Local AI (Ollama) service
- `chat_with_local_model`: Chat with Local AI models
- `recommend_model`: Get model recommendations
- `list_mlx_models`: List MLX models
- `chat_with_mlx_model`: Chat with MLX models
- `list_llamacpp_models`: List LLaMA.cpp models
- `chat_with_llamacpp_model`: Chat with LLaMA.cpp models
- `get_vibe_proxy_status`: Check Vibe proxy
- `query_vibe_proxy`: Query Vibe services

**Phase 4: Intelligence Layer (5 tools)**
- `get_model_performance_metrics`: Get model performance analytics
- `analyse_conversation_patterns`: Analyze conversation data
- `compare_model_responses`: Compare outputs from different models
- `optimise_knowledge_stacks`: Suggest stack optimizations
- `suggest_persona_improvements`: Improve persona definitions

**Phase 5: Tiered AI Workflow / Calibration (4 tools)**
- `run_calibration_test`: Test model capabilities with scoring
- `evaluate_response_quality`: Evaluate response quality (0.0-1.0)
- `identify_handoff_triggers`: Identify patterns requiring escalation
- `get_calibration_history`: Get historical calibration results

**Phase 6: Bloom Behavioral Evaluation (6 tools)**
- `bloom_evaluate_model`: Run Bloom evaluation on local model
- `bloom_check_handoff`: Check if model should hand off to Claude
- `bloom_get_history`: Get past Bloom evaluation results
- `bloom_list_behaviors`: List available behaviors
- `bloom_get_thresholds`: Get quality thresholds by category
- `bloom_validate_model`: Validate model suitability

### Bug Fixes
- Fixed `run_calibration_test` broken import referencing nonexistent `register_phase5_tools` — rewired to use `CALIBRATION_PROMPTS`, `evaluate_response_heuristic`, `init_metrics_db`, and `save_calibration_result` from `phase4_5_tools`
- Fixed `evaluate_response_quality` criteria scoring
- Fixed `import_tool_config` database transaction handling
- Fixed `generate_persona` prompt injection vulnerability
- Improved error handling for service connection timeouts
- Fixed metrics database initialization on first run

### Known Limitations
- `chat_with_local_model`, `chat_with_mlx_model`, and `run_calibration_test` may timeout (30s) if the model is not already loaded in memory due to cold-start latency

### Documentation
- Complete README.md rewrite with installation, usage, architecture
- 8 comprehensive use cases with examples
- Hardware recommendations and performance expectations
- FAQ with common questions
- Architecture diagram showing service components

### Dependencies
- Python 3.10+ (strict requirement)
- MCP SDK v1.0.0+
- psutil 5.9.0+
- Optional: uvicorn, starlette (for HTTP transport)

### Database
- SQLite metrics database at `~/.msty-admin/msty_admin_metrics.db`
- Tables: model_metrics, calibration_tests, handoff_triggers, conversation_analytics
- Automatic initialization on first run

---

## v4.2.0 — 2024

### Added
- Phase 5 Calibration Tools: `run_calibration_test`, `evaluate_response_quality`, `identify_handoff_triggers`, `get_calibration_history`
- SQLite metrics database for storing calibration results and performance metrics
- Quality rubric for response evaluation
- Handoff trigger patterns for escalation

### Improved
- Model recommendation logic with performance metrics
- Error messages for service connection issues
- Documentation for calibration workflow

---

## v4.1.0 — 2024

### Added
- Phase 4 Intelligence Layer: `get_model_performance_metrics`, `analyse_conversation_patterns`, `compare_model_responses`, `optimise_knowledge_stacks`, `suggest_persona_improvements`
- Conversation analytics and pattern detection
- Model comparison capabilities

---

## v4.0.0 — 2024

### Major Changes
- Phase 3 Service Integration redesigned for multiple backends
- Local AI service (Ollama) as primary backend
- Comprehensive health monitoring
- Service status and model availability endpoints

### Added
- Phase 3 Tools (6): `get_service_status`, `list_available_models`, `query_local_ai_service`, `chat_with_local_model`, `recommend_model`
- Service health reports
- Model recommendation system

---

## v3.0.0 — 2024

### Major Changes
- Phase 2 Configuration tools for Msty integration
- Tool export/import functionality
- Persona generation system

### Added
- Phase 2 Tools (4): `export_tool_config`, `sync_claude_preferences`, `generate_persona`, `import_tool_config`
- Configuration synchronization
- Persona management

---

## v2.0.0 — 2024

### Major Changes
- Phase 1 Foundational tools for Msty detection and database access
- Core infrastructure for MCP server

### Added
- Phase 1 Tools (6): `detect_msty_installation`, `read_msty_database`, `list_configured_tools`, `get_model_providers`, `analyse_msty_health`, `get_server_status`
- Msty database query capabilities
- System health analysis

---

## v1.0.0 — 2024

### Initial Release
- MCP server for Msty Studio Desktop
- Basic service integration
- Foundation for tool framework
