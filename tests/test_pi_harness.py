from pathlib import Path


def test_pi_skill_defines_only_the_public_http_contract():
    skill = Path(".pi/skills/vending-machine/SKILL.md").read_text()
    assert skill.startswith("---\nname: vending-machine\n")
    for endpoint in ("POST /env", "GET /env/ENV_ID/status", "DELETE", "make_offer", "set_price", "stock_items"):
        assert endpoint in skill
    assert "engine source" in skill and "private artifacts" in skill
    assert "server is already running" in skill


def test_pi_launcher_loads_only_vending_skill_and_shell_tools():
    launcher = Path("scripts/run_pi_agent.sh").read_text()
    assert "--no-skills --skill" in launcher
    assert "--tools read,bash" in launcher
    assert "--no-context-files" in launcher
    assert "--provider vending-vllm --model qwen3.5-2b" in launcher
    assert 'PI_CODING_AGENT_SESSION_DIR="$project_dir/runs/pi-sessions"' in launcher
    assert "--system-prompt" in launcher and "api_url" in launcher
    assert "do not use ENV_ID literally" in launcher
