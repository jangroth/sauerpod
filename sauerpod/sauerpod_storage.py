from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_dynamodb as _ddb,
    aws_s3 as _s3,
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
            partition_key=_ddb.Attribute(
                name="EpisodeId", type=_ddb.AttributeType.STRING
            ),
            sort_key=_ddb.Attribute(
                name="TimestampUtc", type=_ddb.AttributeType.STRING
            ),
            billing_mode=_ddb.BillingMode.PROVISIONED,
            read_capacity=1,
            write_capacity=1,
            removal_policy=RemovalPolicy.DESTROY,
        )

        #
        # stack outputs
        #
        CfnOutput(
            self,
            "StorageBucketName",
            value=self.storage_bucket.bucket_name,
        )
        CfnOutput(
            self,
            "StorageTableName",
            value=self.storage_table.table_name,
        )
