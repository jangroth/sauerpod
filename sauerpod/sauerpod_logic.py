from aws_cdk import BundlingOptions, CfnOutput, Duration, Stack
from aws_cdk import aws_apigateway as _aws_apigateway
from aws_cdk import aws_dynamodb as _ddb
from aws_cdk import aws_iam as _iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as _logs
from aws_cdk import aws_s3 as _s3
from aws_cdk import aws_stepfunctions as _sfn
from aws_cdk import aws_stepfunctions_tasks as _tasks
from constructs import Construct


class SauerpodLogicStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        storage_bucket: _s3,
        storage_table: _ddb,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        #
        # dispatcher lambda
        #

        dispatcher_lambda = _lambda.Function(
            self,
            "DispatcherLambda",
            runtime=_lambda.Runtime.PYTHON_3_9,
            code=_lambda.Code.from_asset(
                "src",
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_9.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install --no-cache -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            ),
            handler="sauer.dispatcher_handler",
            reserved_concurrent_executions=5,
            environment={"LOGGING": "DEBUG"},
        )
        dispatcher_role = dispatcher_lambda.role
        dispatcher_role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMReadOnlyAccess")
        )

        #
        # downloader lambda
        #

        downloader_lambda = _lambda.Function(
            self,
            "DownloaderLambda",
            runtime=_lambda.Runtime.PYTHON_3_9,
            code=_lambda.Code.from_asset(
                "src",
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_9.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install --no-cache -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            ),
            handler="sauer.downloader_handler",
            reserved_concurrent_executions=5,
            timeout=Duration.minutes(15),
            environment={
                "LOGGING": "DEBUG",
                "STORAGE_BUCKET_NAME": storage_bucket.bucket_name,
                "STORAGE_TABLE_NAME": storage_table.table_name,
            },
        )
        downloader_role = downloader_lambda.role
        downloader_role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMReadOnlyAccess")
        )
        storage_bucket.grant_read_write(downloader_role)
        storage_table.grant_read_write_data(downloader_role)

        #
        # downloader lambda
        #

        podcaster_lambda = _lambda.Function(
            self,
            "Podcaster_Lambda",
            runtime=_lambda.Runtime.PYTHON_3_9,
            code=_lambda.Code.from_asset(
                "src",
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_9.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install --no-cache -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            ),
            handler="sauer.podcaster_handler",
            reserved_concurrent_executions=5,
            timeout=Duration.minutes(15),
            environment={
                "LOGGING": "DEBUG",
                "STORAGE_BUCKET_NAME": storage_bucket.bucket_name,
                "STORAGE_TABLE_NAME": storage_table.table_name,
            },
        )
        podcaster_role = podcaster_lambda.role
        podcaster_role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMReadOnlyAccess")
        )
        storage_bucket.grant_read_write(podcaster_role)
        storage_table.grant_read_data(podcaster_role)

        #
        # statemachine components
        #

        dispatcher_step = _tasks.LambdaInvoke(
            self,
            "DispatcherTask",
            lambda_function=dispatcher_lambda,
            output_path="$.Payload",
        )
        downloader_step = _tasks.LambdaInvoke(
            self,
            "DownloaderTask",
            lambda_function=downloader_lambda,
            output_path="$.Payload",
        )
        podcaster_step = _tasks.LambdaInvoke(
            self,
            "PodcasterTask",
            lambda_function=podcaster_lambda,
            output_path="$.Payload",
        )
        job_succeeded = _sfn.Succeed(self, "Succeeded", comment="succeeded")
        job_failed = _sfn.Fail(self, "Failed", comment="failed")

        # fmt: off
        choice_podcaster = _sfn.Choice(self, "Podcaster?")\
            .when(_sfn.Condition.string_equals("$.status", "SUCCESS"), job_succeeded)\
            .otherwise(job_failed)
        choice_downloader = _sfn.Choice(self, "Downloading Result?")\
            .when(_sfn.Condition.string_equals("$.status", "SUCCESS"), podcaster_step)\
            .when(_sfn.Condition.string_equals("$.status", "NO_ACTION"), podcaster_step)\
            .otherwise(job_failed)
        choice_dispatcher = _sfn.Choice(self, "Dispatching Result?")\
            .when(_sfn.Condition.string_equals("$.status", "FORWARD_TO_DOWNLOADER"), downloader_step)\
            .when(_sfn.Condition.string_equals("$.status", "UNKNOWN_MESSAGE"), job_succeeded)\
            .otherwise(job_failed)
        # fmt: on

        dispatcher_step.next(choice_dispatcher)
        downloader_step.next(choice_downloader)
        podcaster_step.next(choice_podcaster)

        #
        # state machine
        #

        definition = _sfn.Chain.start(dispatcher_step)
        state_machine = _sfn.StateMachine(
            self, "StateMachine", definition=definition, timeout=Duration.minutes(5)
        )

        #
        # bouncer lambda
        #

        # see https://stackoverflow.com/questions/58855739/how-to-install-external-modules-in-a-python-lambda-function-created-by-aws-cdk
        bouncer_lambda = _lambda.Function(
            self,
            "BouncerLambda",
            runtime=_lambda.Runtime.PYTHON_3_9,
            code=_lambda.Code.from_asset(
                "src",
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_9.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install --no-cache -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            ),
            handler="sauer.bouncer_handler",
            reserved_concurrent_executions=5,
            environment={
                "LOGGING": "DEBUG",
                "STATE_MACHINE_ARN": state_machine.state_machine_arn,
            },
        )
        bouncer_role = bouncer_lambda.role
        bouncer_role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMReadOnlyAccess")
        )
        state_machine.grant_start_execution(bouncer_role)

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

        bouncer_lambda_integration = _aws_apigateway.LambdaIntegration(bouncer_lambda)
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
