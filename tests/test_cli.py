"""Tests for the CLI argument parser."""

from supervisor.cli import build_parser


def test_no_args_defaults_to_none_command():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.command is None


def test_serve():
    parser = build_parser()
    args = parser.parse_args(["serve"])
    assert args.command == "serve"


def test_status():
    parser = build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"


def test_start():
    parser = build_parser()
    args = parser.parse_args(["start", "myservice"])
    assert args.command == "start"
    assert args.name == "myservice"


def test_logs_with_options():
    parser = build_parser()
    args = parser.parse_args(["logs", "myservice", "--level", "error", "--limit", "10"])
    assert args.command == "logs"
    assert args.name == "myservice"
    assert args.level == "error"
    assert args.limit == 10


def test_add_with_options():
    parser = build_parser()
    args = parser.parse_args([
        "add", "myapp", "python run.py",
        "--dir", "/home/user/app",
        "--port", "8080",
        "--caddy-subdomain", "myapp",
        "--disabled",
    ])
    assert args.command == "add"
    assert args.name == "myapp"
    assert args.run_command == "python run.py"
    assert args.dir == "/home/user/app"
    assert args.port == 8080
    assert args.caddy_subdomain == "myapp"
    assert args.disabled is True


def test_cron_add():
    parser = build_parser()
    args = parser.parse_args([
        "cron", "add", "backup", "rsync -a /src /dst", "0 2 * * *",
        "--timeout", "600",
    ])
    assert args.command == "cron"
    assert args.cron_command == "add"
    assert args.name == "backup"
    assert args.run_command == "rsync -a /src /dst"
    assert args.schedule == "0 2 * * *"
    assert args.timeout == 600


def test_cron_status():
    parser = build_parser()
    args = parser.parse_args(["cron", "status"])
    assert args.command == "cron"
    assert args.cron_command == "status"


def test_onboard():
    parser = build_parser()
    args = parser.parse_args(["onboard", "myproject", "--model", "sonnet", "--port", "8080"])
    assert args.command == "onboard"
    assert args.project == "myproject"
    assert args.model == "sonnet"
    assert args.port == 8080
