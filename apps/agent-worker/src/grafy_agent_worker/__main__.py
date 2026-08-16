import asyncio
import logging

from grafy_agent_worker.composition import run_worker


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
