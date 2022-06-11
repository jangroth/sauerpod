#!/usr/bin/env bash
set -eux

if [[ -z "${TELEGRAM_API_TOKEN}" ]]; then
    exit 1
fi

BOUNCER_URL=$(aws cloudformation describe-stacks --query 'Stacks[?StackName==`sauerpod`][].Outputs[?OutputKey==`BouncerUrl`].OutputValue' --output text)

# https://core.telegram.org/bots/api#setwebhook
curl "https://api.telegram.org/bot${TELEGRAM_API_TOKEN}/setWebhook?url=${BOUNCER_URL}&drop_pending_updates=True&max_connections=2"
