"""Everything The AJ Index needs on AWS, in one stack.

    browser ──> CloudFront ──┬──> S3                  the website files (web/)
                             └──> /api/* ─> load balancer ─> ECS (Fargate)  the Python API
                                                               │
    EventBridge (daily) ──> ECS task: ajworth.fetch ───────────┴──> RDS Postgres

Money-saving choices (this is a student project lol):
  - no NAT gateway (~$32/month on its own!). The containers sit in public subnets with a
    public IP so they can reach the wiki and pull their image. The database stays in
    private subnets with no internet access at all.
  - smallest sizes everywhere: 0.25 vCPU / 0.5 GB container, db.t4g.micro database
  - ARM (Graviton), which is cheaper, and matches an Apple Silicon Mac so builds are fast
  - a budget alert email if you pass -c alert_email=you@example.com

Tear it ALL down with `cdk destroy` when you're not using it. The database leaves a final
snapshot behind (in case), which you can delete in the RDS console.
"""

from __future__ import annotations

from aws_cdk import (
    CfnOutput, Duration, RemovalPolicy, Stack,
    aws_budgets as budgets,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_ec2 as ec2,
    aws_ecr_assets as ecr_assets,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_events as events,
    aws_events_targets as targets,
    aws_logs as logs,
    aws_rds as rds,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
)
from constructs import Construct

DB_NAME = "ajindex"
ARM = ecs.RuntimePlatform( cpu_architecture=ecs.CpuArchitecture.ARM64,
                           operating_system_family=ecs.OperatingSystemFamily.LINUX )


class AjIndexStack( Stack ):
    def __init__( self, scope: Construct, id: str, **kwargs ):
        super().__init__( scope, id, **kwargs )

        # ------------------------------------------------------------ network
        vpc = ec2.Vpc(
            self, "Vpc", max_azs=2, nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration( name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24 ),
                ec2.SubnetConfiguration( name="db", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24 ),
            ],
        )

        # ------------------------------------------------------------ database
        # the login gets generated and stored in Secrets Manager, I never see or type it
        db = rds.DatabaseInstance(
            self, "Db",
            engine=rds.DatabaseInstanceEngine.postgres( version=rds.PostgresEngineVersion.VER_16 ),
            instance_type=ec2.InstanceType.of( ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.MICRO ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection( subnet_type=ec2.SubnetType.PRIVATE_ISOLATED ),
            credentials=rds.Credentials.from_generated_secret( "aj" ),
            database_name=DB_NAME,
            allocated_storage=20,
            max_allocated_storage=40,           # grows by itself if comments pile up
            storage_encrypted=True,
            multi_az=False,                     # one copy is fine for now (multi-AZ doubles the price)
            publicly_accessible=False,
            backup_retention=Duration.days( 1 ),
            deletion_protection=False,
            removal_policy=RemovalPolicy.SNAPSHOT,
        )

        # how the containers find + log into the database (matches ajworth/db.py)
        db_env = { "DB_NAME": DB_NAME }
        db_secrets = {
            "DB_HOST": ecs.Secret.from_secrets_manager( db.secret, "host" ),
            "DB_PORT": ecs.Secret.from_secrets_manager( db.secret, "port" ),
            "DB_USER": ecs.Secret.from_secrets_manager( db.secret, "username" ),
            "DB_PASSWORD": ecs.Secret.from_secrets_manager( db.secret, "password" ),
        }

        # ------------------------------------------------------------ the app image
        # built from the Dockerfile in the repo root and pushed to ECR during `cdk deploy`
        image = ecs.ContainerImage.from_asset( "..", platform=ecr_assets.Platform.LINUX_ARM64 )
        cluster = ecs.Cluster( self, "Cluster", vpc=vpc )

        # ------------------------------------------------------------ API (ECS + load balancer)
        api = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "Api",
            cluster=cluster,
            cpu=256, memory_limit_mib=512, desired_count=1,
            runtime_platform=ARM,
            public_load_balancer=True,
            assign_public_ip=True,
            task_subnets=ec2.SubnetSelection( subnet_type=ec2.SubnetType.PUBLIC ),
            min_healthy_percent=100,            # start the new version before stopping the old one
            circuit_breaker=ecs.DeploymentCircuitBreaker( rollback=True ),   # bad deploy? auto undo
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=image,
                container_port=8000,
                environment=db_env,
                secrets=db_secrets,
                log_driver=ecs.LogDrivers.aws_logs( stream_prefix="api", log_retention=logs.RetentionDays.ONE_MONTH ),
            ),
        )
        api.target_group.configure_health_check( path="/api/health", healthy_threshold_count=2 )
        api.target_group.set_attribute( "deregistration_delay.timeout_seconds", "10" )   # faster deploys
        db.connections.allow_default_port_from( api.service, "API to Postgres" )

        # ------------------------------------------------------------ daily wiki refresh
        job = ecs.FargateTaskDefinition( self, "RefreshTask", cpu=256, memory_limit_mib=512, runtime_platform=ARM )
        job.add_container(
            "refresh",
            image=image,
            command=[ "python", "-m", "ajworth.fetch" ],
            environment=db_env,
            secrets=db_secrets,
            logging=ecs.LogDrivers.aws_logs( stream_prefix="refresh", log_retention=logs.RetentionDays.ONE_MONTH ),
        )
        job_sg = ec2.SecurityGroup( self, "RefreshSg", vpc=vpc, description="wiki refresh job" )
        db.connections.allow_default_port_from( job_sg, "refresh job to Postgres" )
        events.Rule(
            self, "DailyRefresh",
            schedule=events.Schedule.cron( minute="17", hour="9" ),   # 9:17 UTC = early morning in NY
            targets=[ targets.EcsTask(
                cluster=cluster,
                task_definition=job,
                assign_public_ip=True,
                subnet_selection=ec2.SubnetSelection( subnet_type=ec2.SubnetType.PUBLIC ),
                security_groups=[ job_sg ],
            ) ],
        )

        # ------------------------------------------------------------ website (S3 + CloudFront)
        site = s3.Bucket(
            self, "Site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,   # only CloudFront can read it
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,           # it's just a copy of web/, safe to wipe on destroy
        )
        cdn = cloudfront.Distribution(
            self, "Cdn",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control( site ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.LoadBalancerV2Origin(
                        api.load_balancer, protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,          # the chatbot will POST
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
            },
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,   # US/Canada/Europe edges only = cheaper
        )
        s3deploy.BucketDeployment(
            self, "DeploySite",
            sources=[ s3deploy.Source.asset( "../web", exclude=[ "nginx.conf" ] ) ],
            destination_bucket=site,
            distribution=cdn,                   # clears CloudFront's cache so changes show up right away
            distribution_paths=[ "/*" ],
        )

        # ------------------------------------------------------------ budget alert
        email = self.node.try_get_context( "alert_email" )
        if email:
            limit = float( self.node.try_get_context( "monthly_budget_usd" ) or 50 )
            subscribers = [ budgets.CfnBudget.SubscriberProperty( subscription_type="EMAIL", address=email ) ]
            budgets.CfnBudget(
                self, "Budget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_type="COST", time_unit="MONTHLY",
                    budget_limit=budgets.CfnBudget.SpendProperty( amount=limit, unit="USD" ),
                ),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(
                            notification_type=kind, comparison_operator="GREATER_THAN",
                            threshold=pct, threshold_type="PERCENTAGE" ),
                        subscribers=subscribers,
                    )
                    for kind, pct in [ ( "ACTUAL", 50 ), ( "ACTUAL", 80 ), ( "FORECASTED", 100 ) ]
                ],
            )

        # ------------------------------------------------------------ handy outputs
        CfnOutput( self, "SiteUrl", value=f"https://{cdn.distribution_domain_name}" )
        CfnOutput( self, "ClusterName", value=cluster.cluster_name )
        CfnOutput( self, "RefreshTaskDef", value=job.task_definition_arn )
        CfnOutput( self, "RefreshSecurityGroup", value=job_sg.security_group_id )
        CfnOutput( self, "PublicSubnets", value=",".join( s.subnet_id for s in vpc.public_subnets ) )
