#!/usr/bin/env python3

import aws_cdk as cdk

from sauerpod.sauerpod_storage import SauerpodStorageStack
from sauerpod.sauerpod_logic import SauerpodLogicStack
from sauerpod.sauerpod_publish import SauerpodPublishStack
from sauerpod.sauerpod_publish_alt import SauerpodPublishStackAlt

app = cdk.App()

sss = SauerpodStorageStack(
    scope=app,
    construct_id="sauerpod-storage-stack",
    description="github.com/jangroth/sauerpod - storage bucket and ddb table",
)
sps = SauerpodPublishStack(
    scope=app,
    construct_id="sauerpod-publish-stack",
    storage_bucket=sss.storage_bucket,
    description="github.com/jangroth/sauerpod - cloudfront distribution",
)
sps.add_dependency(sss)
sls = SauerpodLogicStack(
    scope=app,
    construct_id="sauerpod-logic-stack",
    description="github.com/jangroth/sauerpod - state machine with core logic",
)
sls.add_dependency(sps)
slss = SauerpodPublishStackAlt(app, "sauerpod-publish-stack-alt")
slss.add_dependency(sps)

app.synth()
