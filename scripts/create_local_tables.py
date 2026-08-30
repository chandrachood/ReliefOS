"""Create the DynamoDB Local tables used by ReliefOS development."""

from __future__ import annotations

import os

import boto3

ENDPOINT = os.getenv("DYNAMODB_ENDPOINT_URL", "http://localhost:8001")
REGION = os.getenv("AWS_REGION", "us-east-1")

TABLES = {
    os.getenv("CASES_TABLE", "reliefos-cases"): "case_id",
    os.getenv("PEOPLE_TABLE", "reliefos-people"): "person_id",
    os.getenv("RESPONDERS_TABLE", "reliefos-responders"): "responder_id",
    os.getenv("SHELTERS_TABLE", "reliefos-shelters"): "shelter_id",
    os.getenv("MISSIONS_TABLE", "reliefos-missions"): "mission_id",
    os.getenv("AUDIT_TABLE", "reliefos-audit"): "event_id",
}


def main() -> None:
    client = boto3.client(
        "dynamodb",
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    existing = set(client.list_tables()["TableNames"])
    for table_name, key_name in TABLES.items():
        if table_name in existing:
            print(f"exists  {table_name}")
            continue
        client.create_table(
            TableName=table_name,
            AttributeDefinitions=[{"AttributeName": key_name, "AttributeType": "S"}],
            KeySchema=[{"AttributeName": key_name, "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        client.get_waiter("table_exists").wait(TableName=table_name)
        print(f"created {table_name}")


if __name__ == "__main__":
    main()
