# TODO: @samingbar ADD UNIT TESTS FOR THIS WORKFLOW
from __future__ import annotations
import json
import logging
from datetime import timedelta
from typing import Any
from temporalio import workflow
from temporalio.common import RetryPolicy
from .query_info import QueryInfo  # safe to import (stdlib dataclass only)


@workflow.defn(name="recommend_viral_dog_reels")
class RecommendViralReelsWorkflow:
    @workflow.run
    async def run(self, qi: QueryInfo) -> list[dict[str, Any]]:
        act = dict(
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=5,
            ),
        )

        # Call activities by NAME so the workflow sandbox doesn't import third-party libs
        trends = await workflow.execute_activity(
            "fetch_trending_dog_shorts", args=[qi.query, "date", 25], **act
        )
        logging.info(f"Fetched {len(trends)} trends")

        #### TODO: @samingbar REFACTOR INTO THE WORKFLOW CODE ####
        trend_block = await workflow.execute_activity("summarize_trends", args=[trends], **act)
        logging.info(f"Generated trend block: {trend_block}")

        
        raw = await workflow.execute_activity(
            "generate_ideas", args=[qi.dog_profile, trend_block, qi.min_ideas, qi.max_ideas], **act
        )
        logging.info(f"Generated raw ideas: {raw}")
        ideas_raw = await workflow.execute_activity(
            "repair_json_if_needed", args=[raw, qi.min_ideas, qi.max_ideas], **act
        )

        #### TODO: @samingbar REFACTOR INTO THE WORKFLOW CODE####
        logging.info(f"Repaired raw ideas: {ideas_raw}")

        #### TODO: @samingbar REFACTOR INTO THE WORKFLOW CODE####
        ideas = await workflow.execute_activity("normalize_and_validate", args=[ideas_raw], **act)
        logging.info(f"Normalized and validated ideas: {ideas}")


        scripts_bundle = await workflow.execute_activity(
            "generate_scripts_and_rank",
            args=[
                ideas,
                qi.dog_profile,
                False,
                None,
            ],  # save=False; change to True to persist to disk
            **act,
        )

        results = scripts_bundle.get("results", {})
        leaderboard = scripts_bundle.get("leaderboard", [])

        print("\n=== Leaderboard ===")
        for row in leaderboard:
            print(
                f"#{row['rank']:>2}  "
                f"Ref={row['idea_ref']}  "
                f"Score={row['score']:.3f}  "
                f"HookQ={row.get('c_hook_quality_score', 'N/A')}"
            )

        print("\n=== Generated Scripts ===")
        for row in leaderboard:
            ref = row["idea_ref"]
            res = results[ref]

            print("\n" + "=" * 80)
            print(f"RANK {row['rank']} | REF {ref} | SCORE {row['score']:.3f}")

            if res["warnings"]:
                print("Warnings:", "; ".join(res["warnings"]))

            if res["script_json"]:
                print(json.dumps(res["script_json"], ensure_ascii=False, indent=2))
            else:
                print("ERROR:", res["error"] or "Unknown error")
                if res["raw_text"]:
                    preview = res["raw_text"][:400].replace("\n", " ")
                    print("RAW OUTPUT (truncated):", preview, "...")
