import asyncio
import logging

from activities import (
    fetch_trending_dog_shorts,
    generate_ideas,
    generate_scripts_and_rank,
    normalize_and_validate,
    repair_json_if_needed,
    summarize_trends,
)
from temporalio.client import Client
from temporalio.worker import Worker
from workflow import RecommendViralReelsWorkflow


async def main():
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect("localhost:7233")

    worker = Worker(
        client,
        task_queue="viral-dog-reels-queue",
        activities=[
            fetch_trending_dog_shorts,
            summarize_trends,
            generate_ideas,
            repair_json_if_needed,
            normalize_and_validate,
            generate_scripts_and_rank,
        ],
        workflows=[RecommendViralReelsWorkflow],
    )
    logging.info(f"Starting the worker....{client.identity}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
