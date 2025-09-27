import asyncio

from query_info import QueryInfo
from temporalio.client import Client

from .workflow import RecommendViralReelsWorkflow


async def main():
    # Start client
    client = await Client.connect("localhost:7233")
    print("Running Async Completion Workflow. Check Worker for output.")
    query = QueryInfo()

    await client.start_workflow(
        RecommendViralReelsWorkflow.run,
        query,
        id="viral-dog-reels-queue",
        task_queue="viral-dog-reels-queue",
    )


if __name__ == "__main__":
    asyncio.run(main())
