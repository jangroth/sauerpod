#!/usr/bin/env python3

import aws_cdk as cdk

from sauerpod.sauerpod_stack import SauerpodStack

app = cdk.App()
SauerpodStack(app, "sauerpod")

app.synth()
