from aws_cdk import (
    CfnOutput,
    Stack,
    aws_cloudfront as _cloudfront,
    aws_cloudfront_origins as _origins,
    aws_s3 as _s3,
    aws_ssm as _ssm,
)
from constructs import Construct


class SauerpodPublishStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        storage_bucket: _s3.Bucket,  # <--- (1) bucket object imported from other stack
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

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

        #
        # outputs
        #
        CfnOutput(
            self,
            "DistributionDomainNameCfn",
            value=self.distribution.domain_name,
        )
        _ssm.StringParameter(
            self,
            "DistributionDomainNameSsm",
            parameter_name="/sauerpod/aws/distribution_domain_name",
            string_value=self.distribution.domain_name,
        )
