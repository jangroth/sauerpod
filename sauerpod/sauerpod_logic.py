from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_dynamodb as _ddb,
    aws_apigateway as _aws_apigateway,
    aws_logs as _logs,
    aws_s3 as _s3,
    aws_ssm as _ssm,
    aws_stepfunctions as _sfn,
    aws_stepfunctions_tasks as _tasks,
)
from constructs import Construct
from sauerpod.patterns.sauer_lambda import SauerLambda


class SauerpodLogicStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        #
        # inputs
        #
        distribution_domain_name = (
            _ssm.StringParameter.from_string_parameter_attributes(
                self,
                "DistributionDomainNameSsm",
                parameter_name="/sauerpod/aws/distribution_domain_name",
            ).string_value
        )
        storage_bucket_name = _ssm.StringParameter.from_string_parameter_attributes(
            self,
            "StorageBucketNameSsm",
            parameter_name="/sauerpod/aws/storage_bucket_name",
        ).string_value
        storage_bucket = _s3.Bucket.from_bucket_name(
            self, "storage_bucket", storage_bucket_name
        )
        storage_table_name = _ssm.StringParameter.from_string_parameter_attributes(
            self,
            "StorageTableNameSsm",
            parameter_name="/sauerpod/aws/storage_table_name",
        ).string_value
        storage_table = _ddb.Table.from_table_name(
            self, "storage_table", storage_table_name
        )

        #
        # stepfunction lambdas
        #
        dispatcher_lambda = SauerLambda(
            self,
            construct_id="Dispatcher",
            name="DispatcherLambda",
            handler="sauer.dispatcher_handler",
            environment={"LOGGING": "DEBUG"},
            managed_policies=["AmazonSSMReadOnlyAccess"],
        )

        downloader_lambda = SauerLambda(
            self,
            construct_id="Downloader",
            name="DownloaderLambda",
            handler="sauer.downloader_handler",
            timeout_minutes=15,
            environment={
                "LOGGING": "DEBUG",
                "STORAGE_BUCKET_NAME": storage_bucket_name,
                "STORAGE_TABLE_NAME": storage_table_name,
            },
            managed_policies=["AmazonSSMReadOnlyAccess"],
        )
        storage_bucket.grant_read_write(downloader_lambda.function)
        storage_table.grant_read_write_data(downloader_lambda.role)

        commander_lambda = SauerLambda(
            self,
            construct_id="Commander",
            name="CommanderLambda",
            handler="sauer.commander_handler",
            environment={
                "LOGGING": "DEBUG",
                "DISTRIBUTION_DOMAIN_NAME": distribution_domain_name,
                "STORAGE_BUCKET_NAME": storage_bucket_name,
                "STORAGE_TABLE_NAME": storage_table_name,
            },
            managed_policies=["AmazonSSMReadOnlyAccess"],
        )
        storage_bucket.grant_read_write(commander_lambda.function)
        storage_table.grant_read_write_data(commander_lambda.role)

        podcaster_lambda = SauerLambda(
            self,
            construct_id="Podcaster",
            name="PodcasterLambda",
            handler="sauer.podcaster_handler",
            environment={
                "LOGGING": "DEBUG",
                "DISTRIBUTION_DOMAIN_NAME": distribution_domain_name,
                "STORAGE_BUCKET_NAME": storage_bucket_name,
                "STORAGE_TABLE_NAME": storage_table_name,
            },
            managed_policies=["AmazonSSMReadOnlyAccess"],
        )
        storage_bucket.grant_read_write(podcaster_lambda.role)
        storage_table.grant_read_data(podcaster_lambda.role)

        #
        # statemachine wiring
        #
        dispatcher_step = _tasks.LambdaInvoke(
            self,
            "DispatcherTask",
            lambda_function=dispatcher_lambda.function,
            output_path="$.Payload",
        )
        commander_step = _tasks.LambdaInvoke(
            self,
            "CommanderTask",
            lambda_function=commander_lambda.function,
            output_path="$.Payload",
        )
        downloader_step = _tasks.LambdaInvoke(
            self,
            "DownloaderTask",
            lambda_function=downloader_lambda.function,
            output_path="$.Payload",
        )
        podcaster_step = _tasks.LambdaInvoke(
            self,
            "PodcasterTask",
            lambda_function=podcaster_lambda.function,
            output_path="$.Payload",
        )
        job_succeeded = _sfn.Succeed(self, "Succeeded", comment="succeeded")
        job_failed = _sfn.Fail(self, "Failed", comment="failed")

        # fmt: off
        choice_podcaster = _sfn.Choice(self, "Podcaster?")\
            .when(_sfn.Condition.string_equals("$.status", "FINISH"), job_succeeded)\
            .otherwise(job_failed)
        choice_downloader = _sfn.Choice(self, "Downloading Result?")\
            .when(_sfn.Condition.string_equals("$.status", "PODCASTER"), podcaster_step)\
            .when(_sfn.Condition.string_equals("$.status", "FINISH"), job_succeeded)\
            .otherwise(job_failed)
        choice_commander = _sfn.Choice(self, "Commander?")\
            .when(_sfn.Condition.string_equals("$.status", "PODCASTER"), podcaster_step)\
            .when(_sfn.Condition.string_equals("$.status", "FINISH"), job_succeeded)\
            .otherwise(job_failed)
        choice_dispatcher = _sfn.Choice(self, "Dispatching Result?")\
            .when(_sfn.Condition.string_equals("$.status", "DOWNLOADER"), downloader_step)\
            .when(_sfn.Condition.string_equals("$.status", "COMMANDER"), commander_step)\
            .when(_sfn.Condition.string_equals("$.status", "FINISH"), job_succeeded)\
            .otherwise(job_failed)
        # fmt: on

        dispatcher_step.next(choice_dispatcher)
        commander_step.next(choice_commander)
        downloader_step.next(choice_downloader)
        podcaster_step.next(choice_podcaster)

        #
        # state machine
        #
        definition = _sfn.Chain.start(dispatcher_step)
        state_machine = _sfn.StateMachine(
            self, "StateMachine", definition=definition, timeout=Duration.minutes(15)
        )

        #
        # bouncer lambda
        #
        bouncer_lambda = SauerLambda(
            self,
            construct_id="Bouncer",
            name="BouncerLambda",
            handler="sauer.bouncer_handler",
            environment={
                "LOGGING": "DEBUG",
                "STATE_MACHINE_ARN": state_machine.state_machine_arn,
            },
            managed_policies=["AmazonSSMReadOnlyAccess"],
        )
        state_machine.grant_start_execution(bouncer_lambda.role)

        #
        # bouncer API
        #
        sauerpod_api_logs = _logs.LogGroup(self, "ApiLogs")

        sauerpod_api = _aws_apigateway.RestApi(
            self,
            "SauerPodApi",
            rest_api_name="SauerPodApi",
            deploy_options=_aws_apigateway.StageOptions(
                access_log_destination=_aws_apigateway.LogGroupLogDestination(
                    sauerpod_api_logs
                ),
                access_log_format=_aws_apigateway.AccessLogFormat.clf(),
            ),
        )
        sauerpod_resource = sauerpod_api.root.add_resource("sauerpod")

        bouncer_lambda_integration = _aws_apigateway.LambdaIntegration(
            bouncer_lambda.function
        )
        sauerpod_resource.add_method("POST", bouncer_lambda_integration)

        #
        # stack outputs
        #
        CfnOutput(
            self,
            "BouncerUrl",
            value=f"{sauerpod_api.url}sauerpod",
        )
        CfnOutput(self, "StateMachineArn", value=state_machine.state_machine_arn)
