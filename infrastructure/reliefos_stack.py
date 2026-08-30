from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_cloudfront as cloudfront,
)
from aws_cdk import (
    aws_cloudfront_origins as origins,
)
from aws_cdk import (
    aws_cognito as cognito,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_ecs as ecs,
)
from aws_cdk import (
    aws_ecs_patterns as ecs_patterns,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_secretsmanager as secretsmanager,
)
from aws_cdk import (
    aws_sqs as sqs,
)
from constructs import Construct


class ReliefOSStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        auth_mode = str(self.node.try_get_context("auth_mode") or "cognito")
        ai_enabled = str(self.node.try_get_context("ai_triage_enabled") or "false").lower()
        model_id = str(self.node.try_get_context("bedrock_model_id") or "")
        if auth_mode not in {"local", "cognito"}:
            raise ValueError("CDK context auth_mode must be local or cognito")
        if ai_enabled == "true" and not model_id:
            raise ValueError("bedrock_model_id is required when AI triage is enabled")

        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC),
                ec2.SubnetConfiguration(
                    name="application", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ),
            ],
        )

        tables = {
            "CASES_TABLE": self._table("Cases", "case_id"),
            "PEOPLE_TABLE": self._table("People", "person_id"),
            "RESPONDERS_TABLE": self._table("Responders", "responder_id"),
            "SHELTERS_TABLE": self._table("Shelters", "shelter_id"),
            "MISSIONS_TABLE": self._table("Missions", "mission_id"),
            "AUDIT_TABLE": self._table("Audit", "event_id"),
        }

        media_bucket = s3.Bucket(
            self,
            "EvidenceMedia",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(abort_incomplete_multipart_upload_after=Duration.days(1))
            ],
        )

        dead_letter_queue = sqs.Queue(
            self,
            "CaseDeadLetterQueue",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            retention_period=Duration.days(14),
        )
        case_queue = sqs.Queue(
            self,
            "CaseQueue",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            visibility_timeout=Duration.minutes(3),
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(queue=dead_letter_queue, max_receive_count=5),
        )

        user_pool = cognito.UserPool(
            self,
            "UserPool",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True, phone=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            mfa=cognito.Mfa.OPTIONAL,
            password_policy=cognito.PasswordPolicy(min_length=12),
            removal_policy=RemovalPolicy.RETAIN,
        )
        app_client = user_pool.add_client(
            "WebClient",
            auth_flows=cognito.AuthFlow(user_srp=True),
            prevent_user_existence_errors=True,
        )
        for role in [
            "responder",
            "medical",
            "shelter_operator",
            "coordinator",
            "recovery_officer",
        ]:
            cognito.CfnUserPoolGroup(
                self,
                f"Group{role.title().replace('_', '')}",
                group_name=role,
                user_pool_id=user_pool.user_pool_id,
            )

        access_secret = secretsmanager.Secret(
            self,
            "CaseAccessSecret",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                password_length=48, exclude_punctuation=True
            ),
        )

        cluster = ecs.Cluster(
            self,
            "Cluster",
            vpc=vpc,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )
        project_root = str(Path(__file__).resolve().parents[1])
        image = ecs.ContainerImage.from_asset(project_root)

        common_environment = {
            "APP_ENV": "production" if auth_mode == "cognito" else "development",
            "AUTH_MODE": auth_mode,
            "STORAGE_BACKEND": "dynamodb",
            "AWS_REGION": self.region,
            "MEDIA_BUCKET": media_bucket.bucket_name,
            "CASE_QUEUE_URL": case_queue.queue_url,
            "AI_TRIAGE_ENABLED": ai_enabled,
            "BEDROCK_MODEL_ID": model_id,
            "COGNITO_USER_POOL_ID": user_pool.user_pool_id,
            "COGNITO_APP_CLIENT_ID": app_client.user_pool_client_id,
            **{name: table.table_name for name, table in tables.items()},
        }

        api = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "ApiService",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=2,
            public_load_balancer=True,
            assign_public_ip=False,
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=image,
                container_port=8000,
                environment=common_environment,
                secrets={"CASE_ACCESS_SECRET": ecs.Secret.from_secrets_manager(access_secret)},
                log_driver=ecs.LogDrivers.aws_logs(stream_prefix="reliefos-api"),
            ),
            health_check_grace_period=Duration.seconds(60),
        )
        api.target_group.configure_health_check(path="/health/live", healthy_http_codes="200")

        worker_task = ecs.FargateTaskDefinition(self, "WorkerTask", cpu=512, memory_limit_mib=1024)
        worker_task.add_container(
            "Worker",
            image=image,
            command=["python", "-m", "app.worker"],
            environment=common_environment,
            secrets={"CASE_ACCESS_SECRET": ecs.Secret.from_secrets_manager(access_secret)},
            logging=ecs.LogDrivers.aws_logs(stream_prefix="reliefos-worker"),
        )
        ecs.FargateService(
            self,
            "WorkerService",
            cluster=cluster,
            task_definition=worker_task,
            desired_count=1,
            assign_public_ip=False,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
        )

        for task_role in [api.task_definition.task_role, worker_task.task_role]:
            for table in tables.values():
                table.grant_read_write_data(task_role)
            media_bucket.grant_read_write(task_role)
            case_queue.grant_send_messages(task_role)
        case_queue.grant_consume_messages(worker_task.task_role)
        if ai_enabled == "true":
            worker_task.task_role.add_to_principal_policy(
                iam.PolicyStatement(
                    actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                    resources=["*"],
                )
            )

        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.LoadBalancerV2Origin(
                    api.load_balancer,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    http_port=80,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            ),
        )

        cdk.CfnOutput(self, "PortalUrl", value=f"https://{distribution.domain_name}/portal/")
        cdk.CfnOutput(self, "ApiDocsUrl", value=f"https://{distribution.domain_name}/docs")
        cdk.CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId", value=app_client.user_pool_client_id)
        cdk.CfnOutput(self, "AuthenticationMode", value=auth_mode)

    def _table(self, construct_id: str, partition_key: str) -> dynamodb.Table:
        return dynamodb.Table(
            self,
            construct_id,
            partition_key=dynamodb.Attribute(
                name=partition_key, type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            removal_policy=RemovalPolicy.RETAIN,
        )
