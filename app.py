#!/usr/bin/env python3

import aws_cdk as cdk

from sauerpod.sauerpod_storage import SauerpodStorageStack
from sauerpod.sauerpod_logic import SauerpodLogicStack
from sauerpod.sauerpod_publish import SauerpodPublishStack
from sauerpod.sauerpod_publish_alt import SauerpodPublishStackAlt

app = cdk.App()

sss = SauerpodStorageStack(
    app,
    "sauerpod-storage-stack",
)
SauerpodPublishStack(app, "sauerpod-publish-stack", sss.storage_bucket)
SauerpodLogicStack(
    app,
    "sauerpod-logic-stack",
)
SauerpodPublishStackAlt(app, "sauerpod-publish-stack-alt")
app.synth()
