from pathlib import Path


def test_pi_skill_defines_only_the_public_http_contract():
    skill = Path(".pi/skills/vending-machine/SKILL.md").read_text()
    assert skill.startswith("---\nname: vending-machine\n")
    for endpoint in (
        "POST /env",
        "GET /env/ENV_ID/status",
        "DELETE",
        "make_offer",
        "set_price",
        "stock_items",
    ):
        assert endpoint in skill
    assert "Never read server files" in skill
    assert "one API request per `bash` tool call" in skill
    assert "First call must be `POST /env`" in skill
    assert "including `env_` prefix" in skill
    assert "On `ended` or `unavailable`" in skill
    assert "## Controller graph" in skill
    assert "## Daily policy" in skill


def test_pi_launcher_loads_only_vending_skill_and_shell_tools():
    launcher = Path("scripts/run_pi_agent.sh").read_text()
    assert "--no-skills --skill" in launcher
    assert (
        '--no-extensions -e "$project_dir/.pi/extensions/vending-guard.js"' in launcher
    )
    assert "--tools read,bash" in launcher
    assert "--no-context-files" in launcher
    assert "--provider vending-vllm --model qwen3.5-2b" in launcher
    assert 'PI_CODING_AGENT_SESSION_DIR="$project_dir/runs/pi-sessions"' in launcher
    assert "--system-prompt" in launcher and "api_url" in launcher
    assert "do not use ENV_ID literally" in launcher
    assert "Do not ask the user questions or wait for further instructions" in launcher
    assert "Immediately call observe" in launcher


def test_pi_graph_guard_extension_enforces_key_transitions():
    ext = Path(".pi/extensions/vending-guard.js").read_text()
    assert 'isToolCallEventType("bash", event)' in ext
    assert "Graph guard: create environment first with POST /env." in ext
    assert "Graph guard: run observe once before operational actions." in ext
    assert "Graph guard: stock_items requires set_price for that product first." in ext
    assert (
        "Graph guard: stock_items requires an accepted make_offer for that product."
        in ext
    )
