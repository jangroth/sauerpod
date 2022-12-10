from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_dynamodb as _ddb,
    aws_s3 as _s3,
    aws_ssm as _ssm,
)
from constructs import Construct


class SauerpodStorageStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        #
        # storage bucket
        #
        bucket_name = f"{self.account}-{self.region}-sauerpod"
        bucket = _s3.Bucket(
            self,
            "StorageBucket",
            auto_delete_objects=True,
            bucket_name=bucket_name,
            block_public_access=_s3.BlockPublicAccess.BLOCK_ALL,
            encryption=_s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.storage_bucket = bucket

        #
        # storage table
        #
        self.storage_table = _ddb.Table(
            self,
            "StorageTable",
            partition_key=_ddb.Attribute(name="FeedId", type=_ddb.AttributeType.STRING),
            sort_key=_ddb.Attribute(
                name="TimestampUtc", type=_ddb.AttributeType.STRING
            ),
            billing_mode=_ddb.BillingMode.PROVISIONED,
            read_capacity=1,
            write_capacity=1,
            removal_policy=RemovalPolicy.DESTROY,
        )

        #
        # outputs
        #
        CfnOutput(
            self,
            "StorageBucketNameCfn",
            value=self.storage_bucket.bucket_name,
        )
        _ssm.StringParameter(
            self,
            "StorageBucketNameSsm",
            parameter_name="/sauerpod/aws/storage_bucket_name",
            string_value=self.storage_bucket.bucket_name,
        )
        CfnOutput(
            self,
            "StorageTableNameCfn",
            value=self.storage_table.table_name,
        )
        _ssm.StringParameter(
            self,
            "StorageTableNameSsm",
            parameter_name="/sauerpod/aws/storage_table_name",
            string_value=self.storage_table.table_name,
        )
