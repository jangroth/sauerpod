from aws_cdk import BundlingOptions, CfnOutput, Stack
from aws_cdk import aws_iam as _iam
from aws_cdk import aws_lambda as _lambda
from constructs import Construct


class SauerpodStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

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
            environment={"LOGGING": "DEBUG"},
        )
        bouncer_fn_url = bouncer_lambda.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE
        )
        bouncer_role = bouncer_lambda.role
        bouncer_role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMReadOnlyAccess")
        )

        CfnOutput(self, "BouncerUrl", value=bouncer_fn_url.url)
