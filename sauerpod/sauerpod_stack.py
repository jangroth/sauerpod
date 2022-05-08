from aws_cdk import BundlingOptions, CfnOutput, Stack
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
                "lambda",
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_9.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install --no-cache -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            ),
            handler="bouncer.handler",
        )
        fn_url = bouncer_lambda.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE
        )

        CfnOutput(self, "BouncerUrl", value=fn_url.url)
