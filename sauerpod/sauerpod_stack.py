from aws_cdk import BundlingOptions, CfnOutput, Duration, Stack
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
            "Wait 10 Seconds",
            time=_aws_stepfunctions.WaitTime.duration(Duration.seconds(10)),
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
            reserved_concurrent_executions=2,
            environment={
                "LOGGING": "DEBUG",
                "STATE_MACHINE_ARN": state_machine.state_machine_arn,
            },
        )
        bouncer_fn_url = bouncer_lambda.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE
        )
        bouncer_role = bouncer_lambda.role
        bouncer_role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMReadOnlyAccess")
        )
        state_machine.grant_start_execution(bouncer_role)

        #
        # stack outputs
        #

        CfnOutput(self, "BouncerUrl", value=bouncer_fn_url.url)
        CfnOutput(self, "StateMachineArn", value=state_machine.state_machine_arn)
