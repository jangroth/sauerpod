#!/usr/bin/env python3

import aws_cdk as cdk

from sauerpod.sauerpod_long_lived import SauerpodLongLivedStack
from sauerpod.sauerpod_short_lived import SauerpodShortLivedStack

app = cdk.App()
ll_stack = SauerpodLongLivedStack(app, "sauerpod_long_lived")
SauerpodShortLivedStack(app, "sauerpod_short_lived", storage_bucket=ll_stack.storage_bucket)

app.synth()
