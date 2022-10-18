from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_s3 as _s3
from constructs import Construct


class SauerpodLongLivedStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        #
        # storage bucket
        #

        bucket_name = f"{self.account}-{self.region}-sauerpod"
        bucket = _s3.Bucket(
            self,
            "StorageBucket",
            bucket_name=bucket_name,
            encryption=_s3.BucketEncryption.KMS_MANAGED,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.storage_bucket = bucket
