from aws_cdk import (
    BundlingOptions,
    Duration,
    aws_iam as _iam,
    aws_lambda as _lambda,
)
from constructs import Construct
from typing import List


class EasyLambda(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        name: str,
        handler: str,
        environment: dict,
        managed_policies: List[str],
        timeout_minutes: int = 1,
    ) -> None:
        super().__init__(scope, construct_id)

        self.function = _lambda.Function(
            self,
            name,
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
            handler=handler,
            reserved_concurrent_executions=5,
            timeout=Duration.minutes(timeout_minutes),
            environment=environment,
        )
        self.role = self.function.role
        [
            self.role.add_managed_policy(
                _iam.ManagedPolicy.from_aws_managed_policy_name(policy_name)
            )
            for policy_name in managed_policies
        ]
