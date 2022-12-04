#!/usr/bin/env python3

import aws_cdk as cdk

from sauerpod.sauerpod_storage import SauerpodStorageStack
from sauerpod.sauerpod_logic import SauerpodLogicStack
from sauerpod.sauerpod_publish import SauerpodPublishStack

app = cdk.App()

storage_stack = SauerpodStorageStack(app, "sauerpod-storage-stack")
SauerpodLogicStack(
    app,
    "sauerpod-logic-stack",
    storage_bucket=storage_stack.storage_bucket,
    storage_table=storage_stack.storage_table,
)
publish_stack = SauerpodPublishStack(app, "sauerpod-publish-stack")

app.synth()
