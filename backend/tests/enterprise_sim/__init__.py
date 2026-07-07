"""Enterprise-gateway simulator for local end-to-end testing.

Runs a FastAPI server that speaks the same wire protocol as a real
enterprise LLM gateway (ADFS-style password grant → session-JWT →
OpenAI-compat completions) but forwards actual chat completions to the
locally-configured Azure OpenAI deployment.

This lets us exercise the ``enterprise_gateway`` provider adapter in
mars_cmbagent end-to-end without needing real enterprise credentials.
"""
