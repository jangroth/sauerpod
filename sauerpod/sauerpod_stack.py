from aws_cdk import BundlingOptions, CfnOutput, Duration, Stack
from aws_cdk import aws_apigateway as _aws_apigateway
from aws_cdk import aws_iam as _iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as _logs
from aws_cdk import aws_stepfunctions as _aws_stepfunctions
from aws_cdk import aws_stepfunctions_tasks as _tasks

# from aws_cdk import aws_stepfunctions_tasks as _aws_stepfunctions_tasks
from constructs import Construct


class SauerpodStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
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
        # steps definitions
        #

        dispatcher_step = _tasks.LambdaInvoke(
            self, "DispatcherTask", lambda_function=dispatcher_lambda
        )
        job_succeeded = _aws_stepfunctions.Succeed(
            self, "Succeeded", comment="succeeded"
        )
        job_failed = _aws_stepfunctions.Fail(self, "Failed", comment="failed")

        #
        # state machine
        #

        definition = dispatcher_step.next(job_succeeded)
        state_machine = _aws_stepfunctions.StateMachine(
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
