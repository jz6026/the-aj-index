#!/usr/bin/env python3
"""Entry point for `cdk deploy`. All the actual AWS stuff is in stack.py."""

import os

import aws_cdk as cdk

from stack import AjIndexStack

app = cdk.App()
AjIndexStack(
    app, "AjIndex",
    # uses whatever account + region the AWS CLI is logged into (`aws configure`)
    env=cdk.Environment( account=os.environ.get( "CDK_DEFAULT_ACCOUNT" ),
                         region=os.environ.get( "CDK_DEFAULT_REGION", "us-east-1" ) ),
)
cdk.Tags.of( app ).add( "project", "the-aj-index" )   # so it's easy to find in the billing page
app.synth()
