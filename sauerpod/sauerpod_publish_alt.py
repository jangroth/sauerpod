from aws_cdk import (
    CfnOutput,
    Stack,
    aws_cloudfront as _cloudfront,
    aws_cloudfront_origins as _origins,
    aws_s3 as _s3,
    aws_ssm as _ssm,
)
from constructs import Construct


class SauerpodPublishStackAlt(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        #
        # inputs
        #
        storage_bucket_name = _ssm.StringParameter.from_string_parameter_attributes(
            self,
            "StorageBucketNameSsm",
            parameter_name="/sauerpod/aws/storage_bucket_name",
        ).string_value
        storage_bucket = _s3.Bucket.from_bucket_name(
            self, "storage_bucket", storage_bucket_name
        )

        #
        # cloudfront distribution
        #
        self.distribution = _cloudfront.Distribution(
            self,
            "cloudfront_distribution",
            default_behavior=_cloudfront.BehaviorOptions(
                origin=_origins.S3Origin(storage_bucket),
                viewer_protocol_policy=_cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            additional_behaviors={
                "/*.rss": _cloudfront.BehaviorOptions(
                    origin=_origins.S3Origin(storage_bucket),
                    cache_policy=_cloudfront.CachePolicy.CACHING_DISABLED,
                )
            },
            default_root_object="index.html",
        )
        oai = _cloudfront.OriginAccessIdentity(self, "cloudfront_oai")
        storage_bucket.grant_read(oai)

        #
        # outputs
        #
        CfnOutput(
            self,
            "DistributionDomainNameAltCfn",
            value=self.distribution.domain_name,
        )
        _ssm.StringParameter(
            self,
            "DistributionDomainNameAltSsm",
            parameter_name="/sauerpod/aws/distribution_domain_name_alt",
            string_value=self.distribution.domain_name,
        )
