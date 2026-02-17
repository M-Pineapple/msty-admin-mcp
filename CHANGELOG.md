# Changelog

All notable changes to Msty Admin MCP will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.1.1] - 2026-02-17

### Fixed
- **Truncated `phase4_5_tools.py`**: Restored 68 missing lines accidentally removed in v4.1.0 commit `37f34d87`, which truncated `evaluate_response_heuristic()` and the `__all__` export block (fixes [#2](https://github.com/M-Pineapple/msty-admin-mcp/issues/2))

## [4.1.0] - 2025-12-30

### Added
- **Environment Variables**: Configurable settings via environment variables
  - `MSTY_SIDECAR_HOST` - Sidecar API host address (default: `127.0.0.1`)
  - `MSTY_AI_PORT` - Local AI Service port (default: `11964`)
  - `MSTY_PROXY_PORT` - Sidecar proxy port (default: `11932`)
  - `MSTY_TIMEOUT` - API request timeout in seconds (default: `10`)
- Enhanced `make_api_request()` with configurable host parameter
- Improved error logging with `logger.warning()` for connection failures and HTTP errors
- Error response body capture (first 200 chars) for better debugging

### Changed
- Updated README with Environment Variables documentation section
- Example `claude_desktop_config.json` now includes env var configuration

### Fixed
- Removed duplicate `LOCAL_AI_SERVICE_PORT` constant from `phase4_5_tools.py`

## [4.0.1] - 2025-12-27

### Fixed
- Removed Acknowledgements section from README for cleaner public release

## [4.0.0] - 2025-12-27

### Added
- **Phase 5: Tiered AI Workflow** - Complete calibration and handoff system
  - `run_calibration_test` - Test local models against standardised prompts
  - `evaluate_response_quality` - Score responses using heuristic evaluation
  - `identify_handoff_triggers` - Track patterns that should escalate to Claude
  - `get_calibration_history` - Historical test results with statistics

- **Phase 4: Intelligence Layer** - Performance analytics and optimisation
  - `get_model_performance_metrics` - Tokens/sec, latency, error rates
  - `analyse_conversation_patterns` - Privacy-respecting usage analytics
  - `compare_model_responses` - Multi-model comparison with quality scoring
  - `optimise_knowledge_stacks` - Knowledge stack analysis and recommendations
  - `suggest_persona_improvements` - AI-powered persona optimisation

- Metrics database (`~/.msty-admin/msty_admin_metrics.db`) for persistent tracking
- Calibration prompts for 5 categories: reasoning, coding, writing, analysis, creative
- Quality scoring rubric with heuristic evaluation

### Changed
- Total tools increased from 15 to 24
- Server version bumped to 4.0.0
- README completely rewritten for public release with:
  - Detailed use cases and examples
  - Comprehensive FAQ section
  - Hardware recommendations table
  - Architecture diagram

## [3.0.0] - 2025-12-26

### Added
- **Phase 3: Automation Bridge** - Local model integration via Sidecar API
  - `get_sidecar_status` - Sidecar and Local AI Service health check
  - `list_available_models` - Query available models via Ollama-compatible API
  - `query_local_ai_service` - Direct low-level API access
  - `chat_with_local_model` - Send messages with automatic metric tracking
  - `recommend_model` - Hardware-aware model recommendations

### Changed
- Total tools increased from 10 to 15
- Added psutil dependency for process monitoring

## [2.0.0] - 2025-12-25

### Added
- **Phase 2: Configuration Management** - Sync and export tools
  - `export_tool_config` - Export MCP configurations for backup
  - `import_tool_config` - Validate and prepare tools for Msty import
  - `sync_claude_preferences` - Convert Claude preferences to Msty persona
  - `generate_persona` - Create personas from templates (opus, minimal, coder, writer)

### Changed
- Total tools increased from 6 to 10

## [1.0.0] - 2025-12-24

### Added
- **Phase 1: Foundational Tools** - Read-only database access
  - `detect_msty_installation` - Detect Msty Studio paths and status
  - `read_msty_database` - Query conversations, personas, prompts, tools
  - `list_configured_tools` - View MCP toolbox configuration
  - `get_model_providers` - List configured AI providers
  - `analyse_msty_health` - Database integrity and storage analysis
  - `get_server_status` - MCP server info and capabilities

- Initial project structure with FastMCP server
- MIT License
- Basic README documentation

---

## Version History Summary

| Version | Date | Phase | Tools |
|---------|------|-------|-------|
| 4.1.1 | 2026-02-17 | Bugfix | 24 |
| 4.1.0 | 2025-12-30 | Enhancement | 24 |
| 4.0.1 | 2025-12-27 | Bugfix | 24 |
| 4.0.0 | 2025-12-27 | Phase 5 | 24 |
| 3.0.0 | 2025-12-26 | Phase 3 | 15 |
| 2.0.0 | 2025-12-25 | Phase 2 | 10 |
| 1.0.0 | 2025-12-24 | Phase 1 | 6 |

[4.1.1]: https://github.com/M-Pineapple/msty-admin-mcp/compare/v4.1.0...v4.1.1
[4.1.0]: https://github.com/M-Pineapple/msty-admin-mcp/compare/v4.0.1...v4.1.0
[4.0.1]: https://github.com/M-Pineapple/msty-admin-mcp/compare/v4.0.0...v4.0.1
[4.0.0]: https://github.com/M-Pineapple/msty-admin-mcp/compare/v3.0.0...v4.0.0
[3.0.0]: https://github.com/M-Pineapple/msty-admin-mcp/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/M-Pineapple/msty-admin-mcp/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/M-Pineapple/msty-admin-mcp/releases/tag/v1.0.0
