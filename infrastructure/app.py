#!/usr/bin/env python3
import aws_cdk as cdk
from reliefos_stack import ReliefOSStack

app = cdk.App()
ReliefOSStack(app, "ReliefOSMvpStack")
app.synth()
