from aws_cdk import BundlingOptions, CfnOutput, Duration, Stack
from aws_cdk import aws_apigateway as _aws_apigateway
from aws_cdk import aws_iam as _iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_stepfunctions as _aws_stepfunctions

# from aws_cdk import aws_stepfunctions_tasks as _aws_stepfunctions_tasks
from constructs import Construct

# from aws_cdk import


class SauerpodStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        #
        # step functions definitions
        #

        wait_job = _aws_stepfunctions.Wait(
            self,
            "Wait 2 Seconds",
            time=_aws_stepfunctions.WaitTime.duration(Duration.seconds(2)),
        )

        succeed_job = _aws_stepfunctions.Succeed(self, "Succeeded", comment="succeeded")

        #
        # state machine
        #

        definition = wait_job.next(succeed_job)

        state_machine = _aws_stepfunctions.StateMachine(
            self, "StateMachine", definition=definition, timeout=Duration.minutes(5)
        )
        state_machine.state_machine_arn

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

        sauerpod_api = _aws_apigateway.RestApi(
            self, "SauerPodApi", rest_api_name="SauerPodApi"
        )
        bouncer_lambda_integration = sauerpod_api.LambdaIntegration(bouncer_lambda)
        sauerpod_api.root.add_resource("sauerpod").add_method(
            "POST", bouncer_lambda_integration
        )

        #
        # stack outputs
        #
        CfnOutput(self, "RootUrl", value=sauerpod_api.url)
        CfnOutput(
            self,
            "BouncerUrl",
            value=f"https://${sauerpod_api.restApiId}.execute-api.${self.region}.amazonaws.com/sauerpod",
        )
        CfnOutput(self, "StateMachineArn", value=state_machine.state_machine_arn)
