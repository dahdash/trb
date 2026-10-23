"""Deploy to Liara with lia (~/Work/liara): stage the image sources, upload, release, wait.

Usage: ~/Work/liara/.venv/bin/python scripts/deploy.py [--create] [--app torobche-app] [-m MESSAGE]
--create makes the app first (billed: small-g2, Q-008). Production env comes from .env:
the API keys, plus LLM_ENABLED=1 (the LLM runs only in production).
"""
import argparse
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.path.expanduser("~/Work/liara"))
from dotenv import dotenv_values  # noqa: E402
from lia.liara.client import LiaraClient  # noqa: E402
from lia.liara.tools import LiaraTools  # noqa: E402

# Only what the Dockerfile needs; data/ (raw CSVs, built DBs) stays local.
SOURCES = ["Dockerfile", ".dockerignore", "requirements.txt", "app", "etl",
           "starcoach-dataset-v16-cap300-csv.zip"]
ENV_KEYS = ["BOX_API_TOKEN", "NESHAN_API_KEY", "NESHAN_WEB_API_KEY", "LLM_BASE_URL", "LLM_MODEL"]


async def main(args) -> None:
    env = dotenv_values(ROOT / ".env")
    client = LiaraClient(env["LIARA_API_KEY"], team_id=env.get("LIARA_TEAM_ID") or None)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / args.app
        stage.mkdir()
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        for name in SOURCES:
            src = ROOT / name
            if src.is_dir():
                shutil.copytree(src, stage / name, ignore=ignore)
            else:
                shutil.copy2(src, stage / name)
        tools = LiaraTools(client, Path(tmp), Path(os.path.expanduser("~/Work/liara/.lia")))
        try:
            if args.create:
                print(await tools.create_app(args.app, "docker", "small-g2"))
            envs = {k: env[k] for k in ENV_KEYS if env.get(k)}
            envs["LLM_ENABLED"] = "1"
            await client.set_envs(args.app, envs)
            print("envs:", ", ".join(sorted(envs)))
            print(await tools.deploy(args.app, args.app, "docker", 8000, args.message))
        finally:
            await client.aclose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--app", default="torobche-app")
    p.add_argument("--create", action="store_true")
    p.add_argument("-m", "--message", default="")
    asyncio.run(main(p.parse_args()))
